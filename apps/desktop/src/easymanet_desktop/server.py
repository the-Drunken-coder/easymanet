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

from easymanet.diagnostics import export_support_bundle, import_boot_report, run_diagnostics
from easymanet.support_bundle import create_support_bundle

from .mesh import mesh_discover_payload
from .payloads import (
    disks_payload,
    image_update_payload,
    install_image_update_payload,
    state_payload,
    validate_payload,
)

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
            self._send_json(state_payload())
            return
        if parsed.path == "/api/image-updates":
            self._send_json(image_update_payload())
            return
        if parsed.path == "/api/disks":
            query = parse_qs(parsed.query)
            include_all = query.get("all", ["0"])[0] in {"1", "true", "yes"}
            self._send_json(disks_payload(include_all=include_all))
            return
        self._send_static(parsed.path)

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path not in {
            "/api/validate",
            "/api/mesh/discover",
            "/api/support/bundle",
            "/api/diagnostics/run",
            "/api/diagnostics/bundle",
            "/api/diagnostics/import-boot-report",
            "/api/image-updates/install",
        }:
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        try:
            payload = self._read_json()
            if parsed.path == "/api/mesh/discover":
                self._send_json(mesh_discover_payload(payload))
            elif parsed.path == "/api/support/bundle":
                self._send_json(
                    create_support_bundle(
                        config=str(payload.get("config") or ""),
                        node=str(payload.get("node") or ""),
                        boot_report=str(payload.get("boot_report") or ""),
                        output=str(payload.get("output") or ""),
                        include_disks=_bool_payload(payload.get("include_disks", False)),
                    ).to_dict()
                )
            elif parsed.path == "/api/diagnostics/run":
                self._send_json(run_diagnostics(config=str(payload.get("config", "") or "")))
            elif parsed.path == "/api/diagnostics/bundle":
                self._send_json(export_support_bundle(config=str(payload.get("config", "") or "")))
            elif parsed.path == "/api/diagnostics/import-boot-report":
                self._send_json(import_boot_report(source=str(payload.get("source", "") or "")))
            elif parsed.path == "/api/image-updates/install":
                self._send_json(
                    install_image_update_payload(target=str(payload.get("target", "") or ""))
                )
            else:
                self._send_json(validate_payload(payload))
        except ValueError as exc:
            self._send_json({"ok": False, "errors": [str(exc)]}, status=400)
        except Exception as exc:  # noqa: BLE001 - converted into desktop JSON.
            self._send_json({"ok": False, "errors": [str(exc)]}, status=500)

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


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def _bool_payload(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    if isinstance(value, (int, float)):
        return value != 0
    return False
