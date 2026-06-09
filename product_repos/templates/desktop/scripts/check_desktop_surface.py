#!/usr/bin/env python3
from pathlib import Path


root = Path(__file__).resolve().parents[1]
required = [
    "README.md",
    "REPO_GENERATION.md",
    "pyproject.toml",
    "docs/product-direction.md",
    ".github/workflows/ci.yml",
    ".github/workflows/bootstrap-release.yml",
    ".github/workflows/desktop-release.yml",
    "apps/desktop/electron/package.json",
    "apps/desktop/src/easymanet_desktop/server.py",
]

missing = [path for path in required if not (root / path).exists()]
if missing:
    raise SystemExit(f"Missing generated desktop files: {', '.join(missing)}")

readme = (root / "README.md").read_text()
if "local-first" not in readme or "generated" not in readme:
    raise SystemExit("README.md must describe the generated local-first surface")
