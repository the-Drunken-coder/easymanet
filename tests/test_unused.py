import re
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OVERLAY = ROOT / "images" / "openmanet" / "provisioning" / "openwrt-overlay"
DESKTOP_INDEX = ROOT / "apps" / "desktop" / "src" / "easymanet_desktop" / "static" / "index.html"


class _DisabledTabParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.tags: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag != "button":
            return
        attributes = dict(attrs)
        if attributes.get("role") == "tab" and "disabled" in attributes:
            self.tags.append(self.get_starttag_text())


def _overlay_texts() -> dict[Path, str]:
    return {path: path.read_text() for path in OVERLAY.rglob("*") if path.is_file()}


def test_overlay_env_defaults_are_referenced():
    combined = "\n".join(_overlay_texts().values())
    unused = []
    for match in re.finditer(r':\s*"\$\{([A-Z0-9_]+):=', combined):
        var = match.group(1)
        uses = len(re.findall(r"\$\{" + var + r"\b|\$" + var + r"\b", combined))
        if uses <= 1:
            unused.append(var)
    assert unused == [], f"overlay env defaults never used: {unused}"


def test_overlay_shell_functions_have_callers():
    texts = _overlay_texts()
    unused = []
    for path, text in texts.items():
        for match in re.finditer(r"^([A-Za-z_][A-Za-z0-9_]*)\s*\(\)\s*\{", text, re.M):
            name = match.group(1)
            total = sum(len(re.findall(rf"\b{name}\b", body)) for body in texts.values())
            if total <= 1:
                unused.append(f"{path.name}:{name}")
    assert unused == [], f"overlay functions never called: {unused}"


def test_desktop_nav_has_no_disabled_placeholder_tabs():
    parser = _DisabledTabParser()
    parser.feed(DESKTOP_INDEX.read_text())
    assert parser.tags == []
