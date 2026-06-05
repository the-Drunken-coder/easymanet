"""Image download and cache management.

Downloads OpenMANET base images from configured URLs and caches them
locally. Checks for newer versions on each run.

Users configure download URLs in ~/.easymanet/images.json:

{
  "rpi4-mm6108-spi": {
    "url": "https://example.com/openmanet-rpi4-mm6108-spi.img.gz",
    "version": "2025.04",
    "github": "OpenMANET/firmware"
  }
}

Or pass --image-url to flash command.
"""

import json
import os
import sys
import urllib.request
import urllib.error
from urllib.parse import urlparse
import zlib
from pathlib import Path
from typing import Optional, Tuple

from . import __version__
from .format import human_size

CACHE_DIR = Path.home() / ".easymanet" / "images"
IMAGES_MANIFEST = Path.home() / ".easymanet" / "images.json"
VERSION_FILE = Path.home() / ".easymanet" / "version.json"

DEFAULT_EASYMANET_GITHUB_REPO = "the-Drunken-coder/easymanet"
DEFAULT_OPENMANET_GITHUB = "OpenMANET/firmware"

_GITHUB_API_ERRORS = (
    urllib.error.URLError,
    json.JSONDecodeError,
    OSError,
    TimeoutError,
    ValueError,
)


def _debug_note(message: str) -> None:
    print(f"easymanet: {message}", file=sys.stderr)


DEFAULT_IMAGES = {
    "rpi4-mm6108-spi": {
        "description": "OpenMANET for Raspberry Pi 4 + MM6108 SPI",
        "url": "",
        "version": "",
    },
}


def _ensure_cache_dir() -> Path:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    return CACHE_DIR


def _load_images_manifest() -> dict:
    if IMAGES_MANIFEST.exists():
        try:
            return json.loads(IMAGES_MANIFEST.read_text())
        except (json.JSONDecodeError, OSError):
            pass
    return {}


def _save_images_manifest(data: dict) -> None:
    IMAGES_MANIFEST.parent.mkdir(parents=True, exist_ok=True)
    IMAGES_MANIFEST.write_text(json.dumps(data, indent=2))


def get_image_config(target: str) -> Optional[dict]:
    manifest = _load_images_manifest()
    return manifest.get(target)


def set_image_config(target: str, url: str, version: str = "", description: str = "") -> None:
    manifest = _load_images_manifest()
    manifest[target] = {"url": url, "version": version, "description": description}
    _save_images_manifest(manifest)


def check_latest_version(target: str) -> Optional[Tuple[str, str]]:
    info = get_image_config(target) or {}
    if info.get("url"):
        return info.get("version", "latest"), info["url"]

    github_repo = info.get("github") or DEFAULT_OPENMANET_GITHUB
    return _check_github_release(github_repo, target)


def _fetch_github_release(repo: str) -> Optional[dict]:
    try:
        api_url = f"https://api.github.com/repos/{repo}/releases/latest"
        with urllib.request.urlopen(api_url, timeout=15) as resp:
            return json.loads(resp.read().decode())
    except _GITHUB_API_ERRORS as exc:
        _debug_note(f"GitHub release lookup failed for {repo}: {exc}")
        return None


def _pick_release_asset(release: dict, target: str) -> Optional[Tuple[str, str]]:
    version = release.get("tag_name", "")
    if not version:
        return None

    assets = release.get("assets", [])
    exact = f"openmanet-{version}-{target}-squashfs-sysupgrade.img.gz"
    for asset in assets:
        if asset.get("name") == exact:
            return version, asset["browser_download_url"]

    for asset in assets:
        name = asset.get("name", "")
        if (
            target in name
            and "sysupgrade" in name
            and name.endswith(".img.gz")
        ):
            print(f"  Using release asset: {name}")
            return version, asset["browser_download_url"]

    return None


def _check_github_release(repo: str, target: str) -> Optional[Tuple[str, str]]:
    release = _fetch_github_release(repo)
    if not release:
        return None
    result = _pick_release_asset(release, target)
    if not result:
        version = release.get("tag_name", "unknown")
        print(
            f"No matching sysupgrade image for target '{target}' in {repo} release {version}. "
            f"Expected asset like openmanet-{version}-{target}-squashfs-sysupgrade.img.gz"
        )
    return result


def _url_to_filename(url: str) -> str:
    parts = url.rstrip("/").split("/")
    return parts[-1] if parts else "image.img.gz"


def _validate_download_url(url: str) -> None:
    scheme = urlparse(url).scheme.lower()
    if scheme not in {"http", "https"}:
        raise OSError(f"Unsupported image URL scheme: {scheme or '<none>'}")


def download_image(
    target: str,
    version: str,
    url: str,
    force: bool = False,
) -> Path:
    _validate_download_url(url)
    _ensure_cache_dir()
    filename = _url_to_filename(url)
    dest = CACHE_DIR / filename

    if dest.exists() and not force:
        if _valid_cached_image(dest):
            return dest
        dest.unlink()

    print(f"Downloading {target} image ({version})...")
    print(f"  URL: {url}")

    dest.parent.mkdir(parents=True, exist_ok=True)

    try:
        with urllib.request.urlopen(url, timeout=300) as resp:
            total = int(resp.headers.get("Content-Length", 0))
            downloaded = 0
            with open(dest, "wb") as f:
                while True:
                    chunk = resp.read(1024 * 1024)
                    if not chunk:
                        break
                    f.write(chunk)
                    downloaded += len(chunk)
                    if total:
                        pct = int(downloaded / total * 100)
                        print(
                            f"\r  Progress: {pct}% "
                            f"({human_size(downloaded)}/{human_size(total)})",
                            end="",
                            flush=True,
                        )
            print()
    except urllib.error.URLError as e:
        if dest.exists():
            dest.unlink()
        raise OSError(f"Download failed: {e}") from e

    if not _valid_cached_image(dest):
        dest.unlink(missing_ok=True)
        raise OSError(f"Downloaded image failed integrity check: {dest.name}")

    _save_version(target, version)
    print(f"  Saved: {dest}")
    return dest


def get_cached_image(target: str) -> Optional[Path]:
    _ensure_cache_dir()
    info = get_image_config(target)
    if info:
        filename = _url_to_filename(info.get("url", ""))
        if filename:
            cached = CACHE_DIR / filename
            if cached.exists() and _valid_cached_image(cached):
                return cached
    cached = sorted(CACHE_DIR.glob(f"*{target}*"), key=_cache_mtime, reverse=True)
    for path in cached:
        if _valid_cached_image(path):
            return path
    return None


def _cache_mtime(path: Path) -> float:
    try:
        return path.stat().st_mtime
    except OSError:
        return 0.0


def _valid_cached_image(path: Path) -> bool:
    suffix = path.suffix.lower()
    if suffix == ".img":
        try:
            return path.stat().st_size > 0
        except OSError:
            return False
    if suffix != ".gz" or not path.stem.lower().endswith(".img"):
        return False
    try:
        decompressor = zlib.decompressobj(16 + zlib.MAX_WBITS)
        total = 0
        with path.open("rb") as f:
            while not decompressor.eof:
                chunk = f.read(1024 * 1024)
                if not chunk:
                    break
                total += len(decompressor.decompress(chunk))
    except (OSError, zlib.error):
        return False
    return decompressor.eof and total > 0


def _save_version(target: str, version: str) -> None:
    VERSION_FILE.parent.mkdir(parents=True, exist_ok=True)
    data = {}
    if VERSION_FILE.exists():
        try:
            data = json.loads(VERSION_FILE.read_text())
        except (json.JSONDecodeError, OSError):
            pass
    data[target] = version
    VERSION_FILE.write_text(json.dumps(data, indent=2))


def easymanet_update_repo() -> str:
    return os.environ.get("EASYMANET_UPDATE_REPO", DEFAULT_EASYMANET_GITHUB_REPO).strip()


def check_easymanet_update() -> Optional[str]:
    repo = easymanet_update_repo()
    if not repo:
        return None
    try:
        url = f"https://api.github.com/repos/{repo}/releases/latest"
        with urllib.request.urlopen(url, timeout=10) as resp:
            data = json.loads(resp.read().decode())
        latest = data.get("tag_name", "").lstrip("v")
        if latest and latest != __version__:
            return latest
    except _GITHUB_API_ERRORS as exc:
        _debug_note(f"EasyMANET update check failed for {repo}: {exc}")
    return None
