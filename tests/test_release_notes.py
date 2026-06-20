import importlib.util
import io
import sys
import urllib.error
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "tools" / "packaging" / "generate_image_release_notes.py"


def load_release_notes():
    spec = importlib.util.spec_from_file_location("generate_image_release_notes", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_call_openai_reports_http_errors(monkeypatch):
    notes = load_release_notes()

    def fail_urlopen(_request, timeout):
        raise urllib.error.HTTPError(
            url="https://api.openai.com/v1/responses",
            code=500,
            msg="server error",
            hdrs={},
            fp=io.BytesIO(b'{"error":"boom"}'),
        )

    monkeypatch.setattr(notes.urllib.request, "urlopen", fail_urlopen)

    with pytest.raises(SystemExit, match="OpenAI API error 500"):
        notes.call_openai("test-key", "test-model", {"task": "test"})


def test_call_openai_reports_network_errors(monkeypatch):
    notes = load_release_notes()

    def fail_urlopen(_request, timeout):
        raise urllib.error.URLError("network down")

    monkeypatch.setattr(notes.urllib.request, "urlopen", fail_urlopen)

    with pytest.raises(SystemExit, match="OpenAI API unreachable: network down"):
        notes.call_openai("test-key", "test-model", {"task": "test"})


def test_call_openai_reports_invalid_json(monkeypatch):
    notes = load_release_notes()

    class InvalidJsonResponse:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def read(self):
            return b"not json"

    monkeypatch.setattr(notes.urllib.request, "urlopen", lambda _request, timeout: InvalidJsonResponse())

    with pytest.raises(SystemExit, match="OpenAI API returned invalid JSON"):
        notes.call_openai("test-key", "test-model", {"task": "test"})
