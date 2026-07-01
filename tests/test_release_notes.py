import importlib.util
import io
import json
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


class JsonResponse:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def read(self):
        return json.dumps(self.payload).encode()


def test_generate_notes_prefers_opencode_go(monkeypatch):
    notes = load_release_notes()
    calls = []

    def fake_opencode(api_key, model, context):
        calls.append(("opencode", api_key, model, context))
        return "generated with opencode"

    def fake_openai(_api_key, _model, _context):
        raise AssertionError("OpenAI should not be used when OpenCode Go is configured")

    monkeypatch.setenv("OPENCODE_GO_API_KEY", "go-key")
    monkeypatch.setenv("OPENCODE_GO_RELEASE_NOTES_MODEL", "kimi-k2.7-code")
    monkeypatch.setenv("OPENAI_API_KEY", "openai-key")
    monkeypatch.setattr(notes, "call_opencode_go", fake_opencode)
    monkeypatch.setattr(notes, "call_openai", fake_openai)

    assert notes.generate_notes({"task": "test"}) == "generated with opencode"
    assert calls == [("opencode", "go-key", "kimi-k2.7-code", {"task": "test"})]


def test_generate_notes_accepts_general_opencode_key(monkeypatch):
    notes = load_release_notes()

    monkeypatch.setenv("OPENCODE_API_KEY", "shared-opencode-key")
    monkeypatch.setattr(
        notes,
        "call_opencode_go",
        lambda api_key, model, _context: f"{api_key}:{model}",
    )

    assert notes.generate_notes({"task": "test"}) == "shared-opencode-key:deepseek-v4-flash"


def test_call_opencode_go_uses_chat_completions_endpoint(monkeypatch):
    notes = load_release_notes()
    requests = []

    def fake_urlopen(request, timeout):
        requests.append((request, timeout))
        return JsonResponse({"choices": [{"message": {"content": "## User Summary\nGenerated"}}]})

    monkeypatch.setattr(notes.urllib.request, "urlopen", fake_urlopen)

    result = notes.call_opencode_go("test-key", "deepseek-v4-flash", {"task": "test"})

    assert result == "## User Summary\nGenerated"
    request, timeout = requests[0]
    assert timeout == 120
    assert request.full_url == "https://opencode.ai/zen/go/v1/chat/completions"
    assert request.headers["Authorization"] == "Bearer test-key"
    body = json.loads(request.data.decode())
    assert body["model"] == "deepseek-v4-flash"
    assert body["messages"][0]["role"] == "system"
    assert body["messages"][1]["role"] == "user"


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
