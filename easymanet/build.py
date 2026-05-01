"""Docker-backed OpenMANET firmware builds."""

import shlex
import subprocess
import tempfile
from pathlib import Path
from typing import Optional


DEFAULT_OPENMANET_REPO = "https://github.com/OpenMANET/firmware.git"
DEFAULT_OPENMANET_VERSION = "1.6.5"
DEFAULT_BOARD = "ekh-bcm2711"
DEFAULT_TARGET = "rpi4-mm6108-spi"
DEFAULT_BUILDER_IMAGE = "easymanet-openmanet-builder:ubuntu24.04"
DEFAULT_DOCKER_PLATFORM = "linux/amd64"

BUILD_ROOT = Path.home() / ".easymanet" / "build"
DOCKER_CONTEXT_DIR = BUILD_ROOT / "docker"
DEFAULT_CACHE_VOLUME = "easymanet-openmanet-firmware-cache"

APT_PACKAGES = [
    "build-essential",
    "ca-certificates",
    "clang",
    "curl",
    "flex",
    "g++",
    "gawk",
    "gettext",
    "git",
    "libncurses5-dev",
    "libssl-dev",
    "python3",
    "python3-setuptools",
    "rsync",
    "subversion",
    "swig",
    "unzip",
    "file",
    "wget",
    "zlib1g-dev",
]


class BuildError(Exception):
    pass


def build_image(
    output_dir: str,
    openmanet_version: str = DEFAULT_OPENMANET_VERSION,
    board: str = DEFAULT_BOARD,
    target: str = DEFAULT_TARGET,
    repo_url: str = DEFAULT_OPENMANET_REPO,
    jobs: Optional[int] = None,
    clean: bool = False,
    rebuild_builder: bool = False,
    builder_image: str = DEFAULT_BUILDER_IMAGE,
) -> Path:
    import os

    jobs = jobs or max(os.cpu_count() or 1, 1)
    output_path = Path(output_dir).expanduser().resolve()
    output_path.mkdir(parents=True, exist_ok=True)

    overlay_dir = _overlay_dir()
    if not overlay_dir.exists():
        raise BuildError(f"OpenWrt overlay not found: {overlay_dir}")

    _ensure_builder_image(builder_image, force=rebuild_builder)
    _ensure_build_dirs()

    command = _docker_run_command(
        repo_url=repo_url,
        openmanet_version=openmanet_version,
        board=board,
        target=target,
        jobs=jobs,
        overlay_dir=overlay_dir,
        output_dir=output_path,
        clean=clean,
        builder_image=builder_image,
    )

    try:
        subprocess.run(command, check=True, timeout=None)
    except subprocess.CalledProcessError as e:
        raise BuildError(f"Docker build failed: {e}") from e

    artifact = output_path / f"openmanet-{openmanet_version}-{target}-squashfs-sysupgrade.img.gz"
    if artifact.exists():
        return artifact

    built = sorted(output_path.glob(f"openmanet-*-{target}-squashfs-sysupgrade.img.gz"))
    if not built:
        raise BuildError(
            f"No built image found in {output_path} for target {target}. "
            "Check the Docker build logs for the OpenMANET artifact path."
        )
    return built[-1]


def _ensure_build_dirs() -> None:
    BUILD_ROOT.mkdir(parents=True, exist_ok=True)
    DOCKER_CONTEXT_DIR.mkdir(parents=True, exist_ok=True)


def _overlay_dir() -> Path:
    return Path(__file__).resolve().parent.parent / "provisioning" / "openwrt-overlay"


def _ensure_builder_image(image_name: str, force: bool = False) -> None:
    _ensure_build_dirs()
    if force:
        subprocess.run(["docker", "image", "rm", "-f", image_name], capture_output=True)

    exists = subprocess.run(
        ["docker", "image", "inspect", image_name],
        capture_output=True,
        timeout=30,
    )
    if exists.returncode == 0:
        return

    dockerfile = _dockerfile_contents()
    context_dir = Path(tempfile.mkdtemp(prefix="easymanet_docker_", dir=DOCKER_CONTEXT_DIR))
    try:
        dockerfile_path = context_dir / "Dockerfile"
        dockerfile_path.write_text(dockerfile)
        subprocess.run(
            ["docker", "build", "--platform", DEFAULT_DOCKER_PLATFORM, "-t", image_name, str(context_dir)],
            check=True,
            timeout=None,
        )
    except subprocess.CalledProcessError as e:
        raise BuildError(f"Failed to build Docker builder image {image_name}: {e}") from e
    finally:
        _remove_tree(context_dir)


def _dockerfile_contents() -> str:
    packages = " ".join(APT_PACKAGES)
    return f"""FROM ubuntu:24.04
ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update \\
    && apt-get install -y --no-install-recommends {packages} \\
    && rm -rf /var/lib/apt/lists/*
WORKDIR /work
"""


def _docker_run_command(
    repo_url: str,
    openmanet_version: str,
    board: str,
    target: str,
    jobs: int,
    overlay_dir: Path,
    output_dir: Path,
    clean: bool,
    builder_image: str,
) -> list[str]:
    import os

    uid = os.getuid()
    gid = os.getgid()

    script = _container_script(
        repo_url=repo_url,
        openmanet_version=openmanet_version,
        board=board,
        target=target,
        jobs=jobs,
        clean=clean,
    )

    return [
        "docker",
        "run",
        "--rm",
        "--platform",
        DEFAULT_DOCKER_PLATFORM,
        "-e",
        f"HOST_UID={uid}",
        "-e",
        f"HOST_GID={gid}",
        "--mount",
        f"type=volume,source={DEFAULT_CACHE_VOLUME},target=/cache",
        "-v",
        f"{overlay_dir}:/overlay:ro",
        "-v",
        f"{output_dir}:/out",
        builder_image,
        "bash",
        "-lc",
        script,
    ]


def _container_script(
    repo_url: str,
    openmanet_version: str,
    board: str,
    target: str,
    jobs: int,
    clean: bool,
) -> str:
    repo_url_q = shlex.quote(repo_url)
    version_q = shlex.quote(openmanet_version)
    board_q = shlex.quote(board)
    target_q = shlex.quote(target)
    jobs_q = shlex.quote(str(jobs))
    clean_flag = "1" if clean else "0"
    return f"""
set -euo pipefail

REPO_DIR=/cache/openmanet-firmware
TARGET={target_q}
HOST_UID="${{HOST_UID:-0}}"
HOST_GID="${{HOST_GID:-0}}"
export FORCE_UNSAFE_CONFIGURE=1
if [ "{clean_flag}" = "1" ]; then
  rm -rf "$REPO_DIR"
fi

if [ ! -d "$REPO_DIR/.git" ]; then
  git clone {repo_url_q} "$REPO_DIR"
fi

cd "$REPO_DIR"
git fetch --tags origin
git checkout {version_q}
git submodule update --init --recursive

mkdir -p files
rm -rf files/etc/easymanet files/etc/uci-defaults/99-easymanet files/usr/lib/easymanet
mkdir -p files/etc files/etc/uci-defaults files/usr/lib
cp -R /overlay/* files/

./scripts/openmanet_setup.sh -i -b {board_q}
make download
make -j{jobs_q}

artifact="$(find bin/target -type f -name "openmanet-*-${{TARGET}}-squashfs-sysupgrade.img.gz" | sort | tail -n1)"
if [ -z "$artifact" ]; then
  echo "No artifact found for target $TARGET" >&2
  exit 1
fi
cp "$artifact" /out/
chown "$HOST_UID:$HOST_GID" /out/*.img.gz 2>/dev/null || true
"""


def _remove_tree(path: Path) -> None:
    if not path.exists():
        return
    for child in sorted(path.rglob("*"), reverse=True):
        if child.is_file() or child.is_symlink():
            child.unlink(missing_ok=True)
        else:
            try:
                child.rmdir()
            except OSError:
                pass
    try:
        path.rmdir()
    except OSError:
        pass
