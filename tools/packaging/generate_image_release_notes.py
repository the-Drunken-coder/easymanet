#!/usr/bin/env python3
"""Generate image release notes with a configured AI provider."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any


DEFAULT_OPENAI_MODEL = "gpt-5.4-mini"
DEFAULT_OPENCODE_GO_MODEL = "deepseek-v4-flash"
OPENAI_RESPONSES_URL = "https://api.openai.com/v1/responses"
OPENCODE_GO_CHAT_COMPLETIONS_URL = "https://opencode.ai/zen/go/v1/chat/completions"
SYSTEM_PROMPT = (
    "You write concise EasyMANET firmware image release notes. "
    "Use two Markdown sections exactly: User Summary and Technical Appendix. "
    "Do not invent hardware support or include secrets."
)


def main() -> int:
    manifest_path = Path(os.environ.get("IMAGE_MANIFEST", "dist/easymanet-image-release.json"))
    output_path = Path(os.environ.get("RELEASE_NOTES", "dist/release-notes.md"))
    if not manifest_path.exists():
        raise SystemExit(f"Image manifest not found: {manifest_path}")

    context = build_context(manifest_path)
    notes = generate_notes(context)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(notes.rstrip() + "\n")
    return 0


def build_context(manifest_path: Path) -> dict[str, Any]:
    manifest = json.loads(manifest_path.read_text())
    return {
        "task": "Write EasyMANET image release notes with a user summary and a technical appendix.",
        "new_manifest": manifest,
        "source_commit_summary": git_output(["log", "--oneline", "-20"]),
        "provisioning_overlay_diff_summary": git_output([
            "diff",
            "--stat",
            "HEAD~1..HEAD",
            "--",
            "images/openmanet/provisioning",
        ]),
        "test_status": "workflow unit tests completed before release note generation",
        "privacy": "Do not include secrets, credentials, tokens, or private support data.",
    }


def generate_notes(context: dict[str, Any]) -> str:
    opencode_api_key = first_env_value("OPENCODE_GO_API_KEY", "OPENCODE_API_KEY")
    if opencode_api_key:
        model = os.environ.get("OPENCODE_GO_RELEASE_NOTES_MODEL", DEFAULT_OPENCODE_GO_MODEL)
        return call_opencode_go(opencode_api_key, model, context)

    openai_api_key = first_env_value("OPENAI_API_KEY")
    if openai_api_key:
        model = os.environ.get("OPENAI_RELEASE_NOTES_MODEL", DEFAULT_OPENAI_MODEL)
        return call_openai(openai_api_key, model, context)

    raise SystemExit("OPENCODE_GO_API_KEY or OPENAI_API_KEY is required to generate automated release notes")


def call_opencode_go(api_key: str, model: str, context: dict[str, Any]) -> str:
    body = {
        "model": model or DEFAULT_OPENCODE_GO_MODEL,
        "messages": [
            {
                "role": "system",
                "content": SYSTEM_PROMPT,
            },
            {
                "role": "user",
                "content": json.dumps(context, indent=2, sort_keys=True),
            },
        ],
    }
    payload = post_json("OpenCode Go", OPENCODE_GO_CHAT_COMPLETIONS_URL, api_key, body)
    return extract_chat_completion_text("OpenCode Go", payload)


def call_openai(api_key: str, model: str, context: dict[str, Any]) -> str:
    body = {
        "model": model or DEFAULT_OPENAI_MODEL,
        "input": [
            {
                "role": "system",
                "content": SYSTEM_PROMPT,
            },
            {
                "role": "user",
                "content": json.dumps(context, indent=2, sort_keys=True),
            },
        ],
    }
    payload = post_json("OpenAI", OPENAI_RESPONSES_URL, api_key, body)
    return extract_responses_text("OpenAI", payload)


def post_json(provider_name: str, url: str, api_key: str, body: dict[str, Any]) -> dict[str, Any]:
    request = urllib.request.Request(
        url,
        data=json.dumps(body).encode(),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            payload = json.loads(response.read().decode(errors="replace"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode(errors="replace")[:500]
        raise SystemExit(f"{provider_name} API error {exc.code}: {body}") from exc
    except urllib.error.URLError as exc:
        raise SystemExit(f"{provider_name} API unreachable: {exc.reason}") from exc
    except json.JSONDecodeError as exc:
        raise SystemExit(f"{provider_name} API returned invalid JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise SystemExit(f"{provider_name} API returned invalid JSON payload")
    return payload


def extract_responses_text(provider_name: str, payload: dict[str, Any]) -> str:
    text = payload.get("output_text")
    if isinstance(text, str) and text.strip():
        return text
    chunks: list[str] = []
    for item in payload.get("output", []):
        if not isinstance(item, dict):
            continue
        for content in item.get("content", []):
            if not isinstance(content, dict):
                continue
            if content.get("type") in {"output_text", "text"} and content.get("text"):
                chunks.append(str(content["text"]))
    if not chunks:
        raise SystemExit(f"{provider_name} response did not include release note text")
    return "\n".join(chunks)


def extract_chat_completion_text(provider_name: str, payload: dict[str, Any]) -> str:
    for choice in payload.get("choices", []):
        if not isinstance(choice, dict):
            continue
        message = choice.get("message", {})
        if isinstance(message, dict):
            content = message.get("content")
            if isinstance(content, str) and content.strip():
                return content
            if isinstance(content, list):
                chunks = [
                    str(item["text"])
                    for item in content
                    if isinstance(item, dict) and item.get("text")
                ]
                if chunks:
                    return "\n".join(chunks)
        text = choice.get("text")
        if isinstance(text, str) and text.strip():
            return text
    raise SystemExit(f"{provider_name} response did not include release note text")


def first_env_value(*names: str) -> str:
    for name in names:
        value = os.environ.get(name, "").strip()
        if value:
            return value
    return ""


def git_output(args: list[str]) -> str:
    try:
        result = subprocess.run(["git", *args], text=True, capture_output=True, check=False, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return ""
    return result.stdout.strip()


if __name__ == "__main__":
    raise SystemExit(main())
