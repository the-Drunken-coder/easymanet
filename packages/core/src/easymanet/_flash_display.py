"""Display helpers for flash workflow plans."""

from __future__ import annotations

import json
import re
from typing import Any, Optional

SECRET_FIELD_NAMES = {"password", "root_password_hash"}
SECRET_LIST_FIELD_NAMES = {"ssh_authorized_keys"}
SECRET_FIELD_PATTERN = re.compile(
    r"password|passphrase|secret|token|credential|access[_-]?key|"
    r"api[_-]?key|private[_-]?key|psk",
    re.IGNORECASE,
)
REDACTED_VALUE = "<redacted>"


def resolve_flash_ssh_enabled(
    *,
    enable_ssh: bool,
    disable_ssh: bool,
) -> Optional[bool]:
    if disable_ssh:
        return False
    if enable_ssh:
        return True
    return None


def resolve_flash_api_wan_enabled(
    *,
    enable_wan_api: bool,
    disable_wan_api: bool,
) -> bool:
    if disable_wan_api:
        return False
    return bool(enable_wan_api)


def effective_flash_ssh_enabled(
    role: str,
    *,
    enable_ssh: bool,
    disable_ssh: bool,
) -> bool:
    if disable_ssh:
        return False
    if enable_ssh:
        return True
    return role == "gate"


def flash_api_wan_note(
    *,
    api_wan_enabled: bool,
    api_wan_applicable: bool,
    enable_wan_api: bool,
    disable_wan_api: bool,
) -> str:
    if not api_wan_applicable:
        return "not applicable"
    if api_wan_enabled:
        return "yes (--enable-wan-api)"
    if disable_wan_api:
        return "no (--disable-wan-api)"
    return "no (default)"


def flash_ssh_note(
    role: str,
    *,
    enable_ssh: bool,
    disable_ssh: bool,
) -> str:
    if disable_ssh:
        return "no (--disable-ssh)"
    if enable_ssh:
        return "yes (--enable-ssh)"
    if role == "gate":
        return "yes (gate role default)"
    return "no (point role default)"


def redact_provision_for_display(value: Any, field_name: str = "") -> Any:
    secret_field = (
        field_name in SECRET_FIELD_NAMES
        or field_name in SECRET_LIST_FIELD_NAMES
        or SECRET_FIELD_PATTERN.search(field_name) is not None
    )
    if isinstance(value, dict):
        if secret_field and value:
            return REDACTED_VALUE
        return {
            key: redact_provision_for_display(child, str(key))
            for key, child in value.items()
        }
    if isinstance(value, list):
        if secret_field:
            return [REDACTED_VALUE for _item in value]
        return [redact_provision_for_display(item) for item in value]
    if secret_field and value:
        return REDACTED_VALUE
    return value


def render_provision_for_display(
    provision: dict[str, Any],
    *,
    show_secrets: bool = False,
) -> str:
    if show_secrets:
        return json.dumps(provision, indent=2)
    return json.dumps(redact_provision_for_display(provision), indent=2)
