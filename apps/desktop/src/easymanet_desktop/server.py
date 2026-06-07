"""Local desktop console server for EasyMANET."""

import json
import mimetypes
import threading
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib import resources
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

import typer

from easymanet.disks import list_disks
from easymanet.download import CACHE_DIR, IMAGES_MANIFEST, get_cached_image
from easymanet.manifest import ManifestError, load_manifest
from easymanet.platform import check_platform
from easymanet.validate import validate
from easymanet.workspace import resolve_fleet_config, workspace_payload

app = typer.Typer(
    name="easymanet-desktop",
    help="Run the local EasyMANET operator console",
    no_args_is_help=True,
)


@app.callback()
def desktop_root() -> None:
    """Run the local EasyMANET operator console."""


@app.command(name="serve")
def serve_cmd(
    host: str = typer.Option("127.0.0.1", "--host", help="Bind address"),
    port: int = typer.Option(8765, "--port", "-p", help="Bind port"),
    open_browser: bool = typer.Option(
        True,
        "--open-browser/--no-open-browser",
        help="Open the console in the default browser",
    ),
) -> None:
    """Serve the local operator console."""
    server = ThreadingHTTPServer((host, port), _DesktopHandler)
    url = f"http://{host}:{server.server_port}/"
    typer.secho(f"EasyMANET desktop console: {url}", fg=typer.colors.GREEN)
    if open_browser:
        threading.Timer(0.3, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        typer.echo("Stopping EasyMANET desktop console.")
    finally:
        server.server_close()


def main() -> None:
    app()


class _DesktopHandler(BaseHTTPRequestHandler):
    server_version = "EasyMANETDesktop/0.1"

    def log_message(self, fmt: str, *args: object) -> None:
        return

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/api/state":
            self._send_json(_state_payload())
            return
        if parsed.path == "/api/disks":
            query = parse_qs(parsed.query)
            include_all = query.get("all", ["0"])[0] in {"1", "true", "yes"}
            self._send_json(_disks_payload(include_all=include_all))
            return
        self._send_static(parsed.path)

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path != "/api/validate":
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        try:
            payload = self._read_json()
            self._send_json(_validate_payload(payload))
        except ValueError as exc:
            self._send_json({"ok": False, "errors": [str(exc)]}, status=400)

    def _read_json(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0") or "0")
        body = self.rfile.read(length)
        if not body:
            return {}
        data = json.loads(body.decode())
        if not isinstance(data, dict):
            raise ValueError("Request body must be a JSON object")
        return data

    def _send_json(self, payload: dict[str, Any], status: int = 200) -> None:
        body = json.dumps(payload, indent=2).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_static(self, request_path: str) -> None:
        static_root = Path(str(resources.files("easymanet_desktop") / "static")).resolve()
        rel = "index.html" if request_path in {"", "/"} else request_path.lstrip("/")
        path = (static_root / rel).resolve()
        if not _is_relative_to(path, static_root) or not path.is_file():
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        body = path.read_bytes()
        content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def _state_payload() -> dict[str, Any]:
    workspace = workspace_payload()
    images = _configured_images()
    for target, entry in images.items():
        cached = get_cached_image(target)
        entry["cached_path"] = str(cached) if cached else ""
    return {
        "ok": True,
        "workspace": workspace,
        "image_cache_dir": str(CACHE_DIR),
        "image_manifest": str(IMAGES_MANIFEST),
        "images": images,
    }


def _configured_images() -> dict[str, dict[str, Any]]:
    if not IMAGES_MANIFEST.exists():
        return {"rpi4-mm6108-spi": {}}
    try:
        data = json.loads(IMAGES_MANIFEST.read_text())
    except (OSError, json.JSONDecodeError):
        return {"rpi4-mm6108-spi": {}}
    if not isinstance(data, dict):
        return {"rpi4-mm6108-spi": {}}
    return {
        str(target): entry if isinstance(entry, dict) else {}
        for target, entry in data.items()
    } or {"rpi4-mm6108-spi": {}}


def _disks_payload(*, include_all: bool) -> dict[str, Any]:
    try:
        check_platform()
        disks = list_disks(include_all=include_all)
    except Exception as exc:  # noqa: BLE001 - surfaced to the local UI as data.
        return {"ok": False, "errors": [str(exc)], "disks": []}
    return {
        "ok": True,
        "disks": [
            {
                "device": disk.device,
                "model": disk.model,
                "size_human": disk.size_human,
                "removable": disk.removable,
                "mounted": disk.mounted,
                "warnings": disk.warnings,
            }
            for disk in disks
        ],
    }


def _validate_payload(payload: dict[str, Any]) -> dict[str, Any]:
    config = str(payload.get("config", "")).strip()
    node = str(payload.get("node", "")).strip() or None
    if not config:
        raise ValueError("config is required")
    config_path = resolve_fleet_config(config)
    try:
        manifest = load_manifest(str(config_path))
    except ManifestError as exc:
        return {"ok": False, "errors": [str(exc)], "warnings": [], "nodes": []}
    result = validate(manifest, node_name=node)
    return {
        "ok": result.valid,
        "config_path": str(config_path),
        "errors": result.errors,
        "warnings": result.warnings,
        "nodes": manifest.node_names(),
    }


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True
