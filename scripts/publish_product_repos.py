#!/usr/bin/env python3
"""Generate and optionally publish EasyMANET public product repositories."""

from __future__ import annotations

import argparse
import base64
import datetime as dt
import json
import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OWNER = "the-Drunken-coder"
DEFAULT_OUTPUT_DIR = ROOT / "build" / "product-repos"
GITHUB_HOST = "github.com"


@dataclass(frozen=True)
class RepoSpec:
    key: str
    name: str
    description: str
    source_paths: tuple[str, ...]
    generated_files: dict[str, str]
    dispatch_event: str
    release_workflow: str


COMMON_SOURCE_PATHS = (
    ".gitignore",
    "pyproject.toml",
    "README.md",
    "docs",
    "easymanet",
    "examples/three-node-field-mesh.yml",
    "provisioning",
    "scripts/verify_overlay_packaging.py",
    "tests",
)


def _common_generated(repo_name: str, product: str) -> dict[str, str]:
    return {
        "REPO_GENERATION.md": f"""# Generated Repository

This repository is a generated EasyMANET public product surface.

- Product: {product}
- Public repo: `{repo_name}`
- Authoring repo: `the-Drunken-coder/easymanet`

Normal development should happen in the authoring repo. Changes are published
here by the authoring repo publish process so the public product surfaces do
not drift from the shared EasyMANET model.
""",
    }


IMAGE_README = """# EasyMANET Images

Public firmware image factory for EasyMANET-flavored OpenMANET releases.

This repository is generated from `the-Drunken-coder/easymanet`. Its job is to
build, verify, and publish flashable OpenMANET images with the EasyMANET
provisioning overlay included.

## What Lives Here

- OpenMANET image build automation.
- The EasyMANET provisioning overlay.
- Image release workflows.
- Image checksums and release manifests.

The shared CLI, provisioning logic, and tests are copied from the authoring repo
so the image pipeline builds from the same behavior that users flash with.

## Release Flow

The tiny bootstrap workflow accepts an intentional `repository_dispatch` or
manual trigger, then invokes the larger image release workflow. The release
workflow builds the firmware image, generates checksums and a manifest, uploads
the build artifact, and creates a GitHub Release when a release tag is supplied.

Manual image releases can be started from the Actions tab with
`Image Release`.
"""


CLI_README = """# EasyMANET CLI

Public installable CLI and automation surface for EasyMANET.

This repository is generated from `the-Drunken-coder/easymanet`. Its job is to
publish the command-line tool that validates fleet files, renders node
provisioning payloads, lists disks, downloads or builds images, flashes media,
and exposes diagnostics-friendly workflows for humans, scripts, and local AI
agents.

## Install From Source

```bash
python -m pip install -e ".[dev]"
```

## Common Commands

```bash
easymanet validate --config fleet.yml
easymanet render --config fleet.yml --node point01
easymanet disks
easymanet flash --config fleet.yml --node point01 --device /dev/disk4 --base-image ./image.img.gz --dry-run
```

## Release Flow

The tiny bootstrap workflow accepts an intentional `repository_dispatch` or
manual trigger, then invokes the larger CLI release workflow. The release
workflow runs tests, builds the wheel and source distribution, uploads them as
artifacts, and creates a GitHub Release when a release tag is supplied.
"""


DESKTOP_README = """# EasyMANET Desktop

Public desktop operator-console surface for EasyMANET.

This repository is generated from `the-Drunken-coder/easymanet`. It is reserved
for the local-first desktop app that will help users download compatible images,
choose fleet nodes, choose removable media safely, flash nodes, and inspect
local boot or network evidence.

The first generated version intentionally contains product direction and release
plumbing rather than app code. The desktop framework and app internals are still
an authoring-repo decision.

## Release Flow

The tiny bootstrap workflow accepts an intentional `repository_dispatch` or
manual trigger, then invokes the larger desktop release workflow. Until app code
exists, that workflow publishes a provenance artifact only, so the release path
is wired without pretending a desktop binary exists.
"""


CI_WORKFLOW = """name: CI

on:
  push:
  pull_request:

permissions:
  contents: read

jobs:
  test:
    name: Unit tests
    runs-on: ubuntu-24.04
    timeout-minutes: 10

    steps:
      - name: Check out repository
        uses: actions/checkout@34e114876b0b11c390a56381ad16ebd13914f8d5
        with:
          persist-credentials: false

      - name: Set up Python
        uses: actions/setup-python@a309ff8b426b58ec0e2a45f0f869d46889d02405
        with:
          python-version: "3.11"

      - name: Install EasyMANET
        run: |
          python -m pip install --upgrade pip
          pip install -e ".[dev]"

      - name: Import smoke test
        run: python -c "import easymanet; from easymanet.cli import app"

      - name: Run unit tests
        run: pytest -q --cov=easymanet --cov-report=term-missing --cov-fail-under=50

      - name: Syntax-check overlay shell scripts
        run: |
          find provisioning/openwrt-overlay \\
            \\( -name '*.sh' -o -path '*/etc/init.d/*' -o -path '*/etc/uci-defaults/*' \\) \\
            -type f -print0 | xargs -0 sh -n

      - name: Verify overlay files are packaged
        run: python scripts/verify_overlay_packaging.py

  package:
    name: Package smoke
    runs-on: ubuntu-24.04
    timeout-minutes: 10

    steps:
      - name: Check out repository
        uses: actions/checkout@34e114876b0b11c390a56381ad16ebd13914f8d5
        with:
          persist-credentials: false

      - name: Set up Python
        uses: actions/setup-python@a309ff8b426b58ec0e2a45f0f869d46889d02405
        with:
          python-version: "3.11"

      - name: Build package
        run: |
          python -m pip install --upgrade pip build
          python -m build

      - name: Install wheel smoke test
        run: |
          python -m pip install dist/*.whl
          easymanet --help
"""


BOOTSTRAP_IMAGE_WORKFLOW = """name: Bootstrap Image Release

on:
  repository_dispatch:
    types: [easymanet-image-release]
  workflow_dispatch:
    inputs:
      release_tag:
        description: GitHub release tag to create, such as images-v0.1.0
        required: false
        default: ""
      openmanet_version:
        description: OpenMANET tag or branch to build
        required: false
        default: "1.6.5"
      board:
        description: OpenMANET board profile
        required: false
        default: "ekh-bcm2711"
      target:
        description: Firmware target suffix
        required: false
        default: "rpi4-mm6108-spi"
      jobs:
        description: Parallel OpenWrt make jobs inside Docker
        required: false
        default: "2"

permissions:
  actions: write
  contents: read

jobs:
  dispatch:
    name: Dispatch image release workflow
    runs-on: ubuntu-24.04
    timeout-minutes: 5

    steps:
      - name: Dispatch Image Release
        env:
          GH_TOKEN: ${{ github.token }}
          INPUT_RELEASE_TAG: ${{ inputs.release_tag || '' }}
          INPUT_OPENMANET_VERSION: ${{ inputs.openmanet_version || '' }}
          INPUT_BOARD: ${{ inputs.board || '' }}
          INPUT_TARGET: ${{ inputs.target || '' }}
          INPUT_JOBS: ${{ inputs.jobs || '' }}
          PAYLOAD_RELEASE_TAG: ${{ github.event.client_payload.release_tag || '' }}
          PAYLOAD_OPENMANET_VERSION: ${{ github.event.client_payload.openmanet_version || '' }}
          PAYLOAD_BOARD: ${{ github.event.client_payload.board || '' }}
          PAYLOAD_TARGET: ${{ github.event.client_payload.target || '' }}
          PAYLOAD_JOBS: ${{ github.event.client_payload.jobs || '' }}
          PAYLOAD_SOURCE_REPO: ${{ github.event.client_payload.source_repo || '' }}
          PAYLOAD_SOURCE_REF: ${{ github.event.client_payload.source_ref || '' }}
          PAYLOAD_SOURCE_SHA: ${{ github.event.client_payload.source_sha || '' }}
        run: |
          set -euo pipefail
          release_tag="${PAYLOAD_RELEASE_TAG:-$INPUT_RELEASE_TAG}"
          openmanet_version="${PAYLOAD_OPENMANET_VERSION:-${INPUT_OPENMANET_VERSION:-1.6.5}}"
          board="${PAYLOAD_BOARD:-${INPUT_BOARD:-ekh-bcm2711}}"
          target="${PAYLOAD_TARGET:-${INPUT_TARGET:-rpi4-mm6108-spi}}"
          jobs="${PAYLOAD_JOBS:-${INPUT_JOBS:-2}}"
          source_repo="${PAYLOAD_SOURCE_REPO:-unknown}"
          source_ref="${PAYLOAD_SOURCE_REF:-unknown}"
          source_sha="${PAYLOAD_SOURCE_SHA:-unknown}"
          gh workflow run image-release.yml \
            --repo "$GITHUB_REPOSITORY" \
            --field release_tag="$release_tag" \
            --field openmanet_version="$openmanet_version" \
            --field board="$board" \
            --field target="$target" \
            --field jobs="$jobs" \
            --field source_repo="$source_repo" \
            --field source_ref="$source_ref" \
            --field source_sha="$source_sha"
"""


IMAGE_RELEASE_WORKFLOW = """name: Image Release

on:
  workflow_dispatch:
    inputs:
      release_tag:
        description: GitHub release tag to create. Leave blank to upload workflow artifacts only.
        required: false
        default: ""
      openmanet_version:
        description: OpenMANET tag or branch to build
        required: false
        default: "1.6.5"
      board:
        description: OpenMANET board profile
        required: false
        default: "ekh-bcm2711"
      target:
        description: Firmware target suffix
        required: false
        default: "rpi4-mm6108-spi"
      jobs:
        description: Parallel OpenWrt make jobs inside Docker
        required: false
        default: "2"
      clean:
        description: Delete cached OpenMANET source before building
        required: false
        type: boolean
        default: false
      source_repo:
        description: Authoring repository that generated this release
        required: false
        default: "unknown"
      source_ref:
        description: Authoring repository ref
        required: false
        default: "unknown"
      source_sha:
        description: Authoring repository commit SHA
        required: false
        default: "unknown"

permissions:
  contents: write

concurrency:
  group: image-release-${{ github.ref }}
  cancel-in-progress: false

jobs:
  build:
    name: Build firmware image
    runs-on: ubuntu-24.04
    timeout-minutes: 360

    steps:
      - name: Free disk space
        run: |
          sudo rm -rf /usr/share/dotnet
          sudo rm -rf /usr/local/lib/android
          sudo rm -rf /opt/ghc
          sudo rm -rf /opt/hostedtoolcache/CodeQL
          sudo docker image prune --all --force
          df -h

      - name: Check out repository
        uses: actions/checkout@34e114876b0b11c390a56381ad16ebd13914f8d5
        with:
          persist-credentials: false

      - name: Set up Python
        uses: actions/setup-python@a309ff8b426b58ec0e2a45f0f869d46889d02405
        with:
          python-version: "3.11"

      - name: Install EasyMANET
        run: |
          python -m pip install --upgrade pip
          pip install -e ".[dev]"

      - name: Run unit tests
        run: pytest -q

      - name: Prepare OpenMANET cache directory
        run: mkdir -p .openmanet-cache

      - name: Restore OpenMANET build cache
        id: openmanet-cache
        uses: actions/cache/restore@27d5ce7f107fe9357f9df03efb73ab90386fccae
        with:
          path: .openmanet-cache
          key: openmanet-docker-cache-v1-${{ runner.os }}-${{ inputs.board }}-${{ inputs.openmanet_version }}-${{ hashFiles('easymanet/build.py', 'pyproject.toml', 'provisioning/extra-packages.txt', 'provisioning/openwrt-overlay/**') }}
          restore-keys: |
            openmanet-docker-cache-v1-${{ runner.os }}-${{ inputs.board }}-${{ inputs.openmanet_version }}-
            openmanet-docker-cache-v1-${{ runner.os }}-${{ inputs.board }}-

      - name: Build EasyMANET-flavored OpenMANET image
        id: build_image
        env:
          OPENMANET_VERSION: ${{ inputs.openmanet_version }}
          BOARD: ${{ inputs.board }}
          TARGET: ${{ inputs.target }}
          JOBS: ${{ inputs.jobs }}
          CLEAN: ${{ inputs.clean }}
        run: |
          set -euo pipefail
          case "$OPENMANET_VERSION" in (""|*[!A-Za-z0-9._/-]*) echo "Invalid openmanet_version"; exit 1;; esac
          case "$BOARD" in (""|*[!A-Za-z0-9._-]*) echo "Invalid board"; exit 1;; esac
          case "$TARGET" in (""|*[!A-Za-z0-9._-]*) echo "Invalid target"; exit 1;; esac
          case "$JOBS" in (""|*[!0-9]*) echo "Invalid jobs"; exit 1;; esac
          if [ "$JOBS" -lt 1 ]; then
            echo "Invalid jobs"
            exit 1
          fi
          args=(
            image build
            --output-dir dist
            --openmanet-version "$OPENMANET_VERSION"
            --board "$BOARD"
            --target "$TARGET"
            --cache-dir .openmanet-cache
            --jobs "$JOBS"
          )
          if [ "$CLEAN" = "true" ]; then
            args+=(--clean)
          fi
          easymanet "${args[@]}"

      - name: Save OpenMANET build cache
        if: steps.build_image.outcome == 'success' && steps.openmanet-cache.outputs.cache-hit != 'true'
        uses: actions/cache/save@27d5ce7f107fe9357f9df03efb73ab90386fccae
        with:
          path: .openmanet-cache
          key: ${{ steps.openmanet-cache.outputs.cache-primary-key }}

      - name: Generate release manifest
        env:
          RELEASE_TAG: ${{ inputs.release_tag }}
          OPENMANET_VERSION: ${{ inputs.openmanet_version }}
          BOARD: ${{ inputs.board }}
          TARGET: ${{ inputs.target }}
          SOURCE_REPO: ${{ inputs.source_repo }}
          SOURCE_REF: ${{ inputs.source_ref }}
          SOURCE_SHA: ${{ inputs.source_sha }}
        run: |
          python - <<'PY'
          import datetime as dt
          import hashlib
          import json
          import os
          from pathlib import Path

          dist = Path("dist")
          artifacts = []
          for path in sorted(dist.glob("*.img.gz")):
              digest = hashlib.sha256(path.read_bytes()).hexdigest()
              sha_path = path.with_suffix(path.suffix + ".sha256")
              sha_path.write_text(f"{digest}  {path.name}\\n")
              artifacts.append({"name": path.name, "sha256": digest, "bytes": path.stat().st_size})

          manifest = {
              "schema_version": 1,
              "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
              "release_tag": os.environ["RELEASE_TAG"],
              "openmanet_version": os.environ["OPENMANET_VERSION"],
              "board": os.environ["BOARD"],
              "target": os.environ["TARGET"],
              "source_repo": os.environ["SOURCE_REPO"],
              "source_ref": os.environ["SOURCE_REF"],
              "source_sha": os.environ["SOURCE_SHA"],
              "public_repo": os.environ["GITHUB_REPOSITORY"],
              "public_sha": os.environ["GITHUB_SHA"],
              "run_id": os.environ["GITHUB_RUN_ID"],
              "artifacts": artifacts,
          }
          (dist / "easymanet-image-manifest.json").write_text(json.dumps(manifest, indent=2) + "\\n")
          PY

      - name: Upload firmware artifacts
        uses: actions/upload-artifact@043fb46d1a93c77aae656e7c1c64a875d1fc6a0a
        with:
          name: easymanet-image-${{ inputs.openmanet_version }}-${{ inputs.target }}
          path: |
            dist/*.img.gz
            dist/*.sha256
            dist/easymanet-image-manifest.json
          retention-days: 14
          if-no-files-found: error

      - name: Create GitHub release
        if: inputs.release_tag != ''
        env:
          GH_TOKEN: ${{ github.token }}
          RELEASE_TAG: ${{ inputs.release_tag }}
          OPENMANET_VERSION: ${{ inputs.openmanet_version }}
          TARGET: ${{ inputs.target }}
          SOURCE_REPO: ${{ inputs.source_repo }}
          SOURCE_REF: ${{ inputs.source_ref }}
          SOURCE_SHA: ${{ inputs.source_sha }}
        run: |
          set -euo pipefail
          notes="$(mktemp)"
          {
            echo "EasyMANET image release for OpenMANET ${OPENMANET_VERSION} (${TARGET})."
            echo
            echo "Generated from ${SOURCE_REPO}@${SOURCE_REF} (${SOURCE_SHA})."
          } > "$notes"
          gh release create "$RELEASE_TAG" dist/* \
            --repo "$GITHUB_REPOSITORY" \
            --title "$RELEASE_TAG" \
            --notes-file "$notes"
"""


BOOTSTRAP_CLI_WORKFLOW = """name: Bootstrap CLI Release

on:
  repository_dispatch:
    types: [easymanet-cli-release]
  workflow_dispatch:
    inputs:
      release_tag:
        description: GitHub release tag to create, such as cli-v0.1.0
        required: false
        default: ""

permissions:
  actions: write
  contents: read

jobs:
  dispatch:
    name: Dispatch CLI release workflow
    runs-on: ubuntu-24.04
    timeout-minutes: 5

    steps:
      - name: Dispatch CLI Release
        env:
          GH_TOKEN: ${{ github.token }}
          INPUT_RELEASE_TAG: ${{ inputs.release_tag || '' }}
          PAYLOAD_RELEASE_TAG: ${{ github.event.client_payload.release_tag || '' }}
          PAYLOAD_SOURCE_REPO: ${{ github.event.client_payload.source_repo || '' }}
          PAYLOAD_SOURCE_REF: ${{ github.event.client_payload.source_ref || '' }}
          PAYLOAD_SOURCE_SHA: ${{ github.event.client_payload.source_sha || '' }}
        run: |
          set -euo pipefail
          release_tag="${PAYLOAD_RELEASE_TAG:-$INPUT_RELEASE_TAG}"
          source_repo="${PAYLOAD_SOURCE_REPO:-unknown}"
          source_ref="${PAYLOAD_SOURCE_REF:-unknown}"
          source_sha="${PAYLOAD_SOURCE_SHA:-unknown}"
          gh workflow run cli-release.yml \
            --repo "$GITHUB_REPOSITORY" \
            --field release_tag="$release_tag" \
            --field source_repo="$source_repo" \
            --field source_ref="$source_ref" \
            --field source_sha="$source_sha"
"""


CLI_RELEASE_WORKFLOW = """name: CLI Release

on:
  workflow_dispatch:
    inputs:
      release_tag:
        description: GitHub release tag to create. Leave blank to upload workflow artifacts only.
        required: false
        default: ""
      source_repo:
        description: Authoring repository that generated this release
        required: false
        default: "unknown"
      source_ref:
        description: Authoring repository ref
        required: false
        default: "unknown"
      source_sha:
        description: Authoring repository commit SHA
        required: false
        default: "unknown"

permissions:
  contents: write

jobs:
  package:
    name: Build CLI package
    runs-on: ubuntu-24.04
    timeout-minutes: 15

    steps:
      - name: Check out repository
        uses: actions/checkout@34e114876b0b11c390a56381ad16ebd13914f8d5
        with:
          persist-credentials: false

      - name: Set up Python
        uses: actions/setup-python@a309ff8b426b58ec0e2a45f0f869d46889d02405
        with:
          python-version: "3.11"

      - name: Install dependencies
        run: |
          python -m pip install --upgrade pip build
          pip install -e ".[dev]"

      - name: Run tests
        run: pytest -q

      - name: Build distributions
        run: python -m build

      - name: Install wheel smoke test
        run: |
          python -m pip install --force-reinstall dist/*.whl
          easymanet --help

      - name: Generate release manifest
        env:
          RELEASE_TAG: ${{ inputs.release_tag }}
          SOURCE_REPO: ${{ inputs.source_repo }}
          SOURCE_REF: ${{ inputs.source_ref }}
          SOURCE_SHA: ${{ inputs.source_sha }}
        run: |
          python - <<'PY'
          import datetime as dt
          import hashlib
          import json
          import os
          from pathlib import Path

          artifacts = []
          for path in sorted(Path("dist").iterdir()):
              if path.is_file():
                  artifacts.append({
                      "name": path.name,
                      "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                      "bytes": path.stat().st_size,
                  })
          manifest = {
              "schema_version": 1,
              "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
              "release_tag": os.environ["RELEASE_TAG"],
              "source_repo": os.environ["SOURCE_REPO"],
              "source_ref": os.environ["SOURCE_REF"],
              "source_sha": os.environ["SOURCE_SHA"],
              "public_repo": os.environ["GITHUB_REPOSITORY"],
              "public_sha": os.environ["GITHUB_SHA"],
              "run_id": os.environ["GITHUB_RUN_ID"],
              "artifacts": artifacts,
          }
          Path("dist/easymanet-cli-manifest.json").write_text(json.dumps(manifest, indent=2) + "\\n")
          PY

      - name: Upload package artifacts
        uses: actions/upload-artifact@043fb46d1a93c77aae656e7c1c64a875d1fc6a0a
        with:
          name: easymanet-cli-package
          path: dist/*
          retention-days: 14
          if-no-files-found: error

      - name: Create GitHub release
        if: inputs.release_tag != ''
        env:
          GH_TOKEN: ${{ github.token }}
          RELEASE_TAG: ${{ inputs.release_tag }}
          SOURCE_REPO: ${{ inputs.source_repo }}
          SOURCE_REF: ${{ inputs.source_ref }}
          SOURCE_SHA: ${{ inputs.source_sha }}
        run: |
          set -euo pipefail
          notes="$(mktemp)"
          {
            echo "EasyMANET CLI package release."
            echo
            echo "Generated from ${SOURCE_REPO}@${SOURCE_REF} (${SOURCE_SHA})."
          } > "$notes"
          gh release create "$RELEASE_TAG" dist/* \
            --repo "$GITHUB_REPOSITORY" \
            --title "$RELEASE_TAG" \
            --notes-file "$notes"
"""


DESKTOP_CI_WORKFLOW = """name: CI

on:
  push:
  pull_request:

permissions:
  contents: read

jobs:
  docs:
    name: Generated surface checks
    runs-on: ubuntu-24.04
    timeout-minutes: 5

    steps:
      - name: Check out repository
        uses: actions/checkout@34e114876b0b11c390a56381ad16ebd13914f8d5
        with:
          persist-credentials: false

      - name: Set up Python
        uses: actions/setup-python@a309ff8b426b58ec0e2a45f0f869d46889d02405
        with:
          python-version: "3.11"

      - name: Check generated desktop surface
        run: python scripts/check_desktop_surface.py
"""


BOOTSTRAP_DESKTOP_WORKFLOW = """name: Bootstrap Desktop Release

on:
  repository_dispatch:
    types: [easymanet-desktop-release]
  workflow_dispatch:
    inputs:
      release_tag:
        description: GitHub release tag to create, such as desktop-v0.1.0
        required: false
        default: ""

permissions:
  actions: write
  contents: read

jobs:
  dispatch:
    name: Dispatch desktop release workflow
    runs-on: ubuntu-24.04
    timeout-minutes: 5

    steps:
      - name: Dispatch Desktop Release
        env:
          GH_TOKEN: ${{ github.token }}
          INPUT_RELEASE_TAG: ${{ inputs.release_tag || '' }}
          PAYLOAD_RELEASE_TAG: ${{ github.event.client_payload.release_tag || '' }}
          PAYLOAD_SOURCE_REPO: ${{ github.event.client_payload.source_repo || '' }}
          PAYLOAD_SOURCE_REF: ${{ github.event.client_payload.source_ref || '' }}
          PAYLOAD_SOURCE_SHA: ${{ github.event.client_payload.source_sha || '' }}
        run: |
          set -euo pipefail
          release_tag="${PAYLOAD_RELEASE_TAG:-$INPUT_RELEASE_TAG}"
          source_repo="${PAYLOAD_SOURCE_REPO:-unknown}"
          source_ref="${PAYLOAD_SOURCE_REF:-unknown}"
          source_sha="${PAYLOAD_SOURCE_SHA:-unknown}"
          gh workflow run desktop-release.yml \
            --repo "$GITHUB_REPOSITORY" \
            --field release_tag="$release_tag" \
            --field source_repo="$source_repo" \
            --field source_ref="$source_ref" \
            --field source_sha="$source_sha"
"""


DESKTOP_RELEASE_WORKFLOW = """name: Desktop Release

on:
  workflow_dispatch:
    inputs:
      release_tag:
        description: GitHub release tag to create. Leave blank to upload workflow artifacts only.
        required: false
        default: ""
      source_repo:
        description: Authoring repository that generated this release
        required: false
        default: "unknown"
      source_ref:
        description: Authoring repository ref
        required: false
        default: "unknown"
      source_sha:
        description: Authoring repository commit SHA
        required: false
        default: "unknown"

permissions:
  contents: write

jobs:
  provenance:
    name: Desktop provenance placeholder
    runs-on: ubuntu-24.04
    timeout-minutes: 5

    steps:
      - name: Check out repository
        uses: actions/checkout@34e114876b0b11c390a56381ad16ebd13914f8d5
        with:
          persist-credentials: false

      - name: Generate provenance artifact
        env:
          RELEASE_TAG: ${{ inputs.release_tag }}
          SOURCE_REPO: ${{ inputs.source_repo }}
          SOURCE_REF: ${{ inputs.source_ref }}
          SOURCE_SHA: ${{ inputs.source_sha }}
        run: |
          mkdir -p dist
          python - <<'PY'
          import datetime as dt
          import json
          import os
          from pathlib import Path

          manifest = {
              "schema_version": 1,
              "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
              "release_tag": os.environ["RELEASE_TAG"],
              "source_repo": os.environ["SOURCE_REPO"],
              "source_ref": os.environ["SOURCE_REF"],
              "source_sha": os.environ["SOURCE_SHA"],
              "public_repo": os.environ["GITHUB_REPOSITORY"],
              "public_sha": os.environ["GITHUB_SHA"],
              "run_id": os.environ["GITHUB_RUN_ID"],
              "status": "desktop app code has not been published yet",
          }
          Path("dist/easymanet-desktop-provenance.json").write_text(json.dumps(manifest, indent=2) + "\\n")
          PY

      - name: Upload provenance artifact
        uses: actions/upload-artifact@043fb46d1a93c77aae656e7c1c64a875d1fc6a0a
        with:
          name: easymanet-desktop-provenance
          path: dist/*
          retention-days: 14
          if-no-files-found: error

      - name: Create GitHub release
        if: inputs.release_tag != ''
        env:
          GH_TOKEN: ${{ github.token }}
          RELEASE_TAG: ${{ inputs.release_tag }}
          SOURCE_REPO: ${{ inputs.source_repo }}
          SOURCE_REF: ${{ inputs.source_ref }}
          SOURCE_SHA: ${{ inputs.source_sha }}
        run: |
          set -euo pipefail
          notes="$(mktemp)"
          {
            echo "EasyMANET desktop release plumbing placeholder."
            echo
            echo "No desktop app binary exists yet."
            echo "Generated from ${SOURCE_REPO}@${SOURCE_REF} (${SOURCE_SHA})."
          } > "$notes"
          gh release create "$RELEASE_TAG" dist/* \
            --repo "$GITHUB_REPOSITORY" \
            --title "$RELEASE_TAG" \
            --notes-file "$notes"
"""


DESKTOP_PRODUCT_DOC = """# Desktop Product Direction

EasyMANET Desktop is intended to be a local-first operator console. It should
share the CLI's safety model and transparent project files rather than becoming
a separate cloud control plane.

Expected first workflows:

- Discover compatible image releases.
- Download and cache images locally.
- Validate fleet configuration.
- Select a fleet node.
- Select a removable disk safely.
- Flash and eject media.
- Read boot reports and local diagnostics.

This generated repo exists now so release and issue-reporting infrastructure can
be wired before framework-specific app code lands.
"""


DESKTOP_CHECK_SCRIPT = """#!/usr/bin/env python3
from pathlib import Path


root = Path(__file__).resolve().parents[1]
required = [
    "README.md",
    "REPO_GENERATION.md",
    "docs/product-direction.md",
    ".github/workflows/ci.yml",
    ".github/workflows/bootstrap-release.yml",
    ".github/workflows/desktop-release.yml",
]

missing = [path for path in required if not (root / path).exists()]
if missing:
    raise SystemExit(f"Missing generated desktop files: {', '.join(missing)}")

readme = (root / "README.md").read_text()
if "local-first" not in readme or "generated" not in readme:
    raise SystemExit("README.md must describe the generated local-first surface")
"""


REPO_SPECS = {
    "images": RepoSpec(
        key="images",
        name="easymanet-images",
        description="Public firmware image factory for EasyMANET/OpenMANET releases.",
        source_paths=COMMON_SOURCE_PATHS
        + (
            ".github/workflows/build-openmanet-image.yml",
            ".github/workflows/prove-overlay-weekly.yml",
        ),
        generated_files={
            **_common_generated("easymanet-images", "firmware image releases"),
            "README.md": IMAGE_README,
            ".github/workflows/ci.yml": CI_WORKFLOW,
            ".github/workflows/bootstrap-release.yml": BOOTSTRAP_IMAGE_WORKFLOW,
            ".github/workflows/image-release.yml": IMAGE_RELEASE_WORKFLOW,
        },
        dispatch_event="easymanet-image-release",
        release_workflow="image-release.yml",
    ),
    "cli": RepoSpec(
        key="cli",
        name="easymanet-cli",
        description="Public CLI and automation surface for EasyMANET.",
        source_paths=COMMON_SOURCE_PATHS,
        generated_files={
            **_common_generated("easymanet-cli", "CLI and automation"),
            "README.md": CLI_README,
            ".github/workflows/ci.yml": CI_WORKFLOW,
            ".github/workflows/bootstrap-release.yml": BOOTSTRAP_CLI_WORKFLOW,
            ".github/workflows/cli-release.yml": CLI_RELEASE_WORKFLOW,
        },
        dispatch_event="easymanet-cli-release",
        release_workflow="cli-release.yml",
    ),
    "desktop": RepoSpec(
        key="desktop",
        name="easymanet-desktop",
        description="Public local-first desktop operator console for EasyMANET.",
        source_paths=(),
        generated_files={
            **_common_generated("easymanet-desktop", "desktop operator console"),
            "README.md": DESKTOP_README,
            "docs/product-direction.md": DESKTOP_PRODUCT_DOC,
            "scripts/check_desktop_surface.py": DESKTOP_CHECK_SCRIPT,
            ".github/workflows/ci.yml": DESKTOP_CI_WORKFLOW,
            ".github/workflows/bootstrap-release.yml": BOOTSTRAP_DESKTOP_WORKFLOW,
            ".github/workflows/desktop-release.yml": DESKTOP_RELEASE_WORKFLOW,
        },
        dispatch_event="easymanet-desktop-release",
        release_workflow="desktop-release.yml",
    ),
}


def run(
    args: list[str],
    *,
    cwd: Path | None = None,
    env: dict[str, str] | None = None,
    input_text: str | None = None,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args,
        cwd=cwd,
        env=env,
        input=input_text,
        text=True,
        check=check,
        capture_output=True,
    )


def git_output(args: list[str], *, cwd: Path = ROOT) -> str:
    return run(["git", *args], cwd=cwd).stdout.strip()


def selected_specs(product: str) -> list[RepoSpec]:
    if product == "all":
        return [REPO_SPECS["images"], REPO_SPECS["cli"], REPO_SPECS["desktop"]]
    return [REPO_SPECS[product]]


def copy_source_path(rel_path: str, target_root: Path) -> None:
    src = ROOT / rel_path
    dest = target_root / rel_path
    if not src.exists():
        raise FileNotFoundError(f"Source path does not exist: {rel_path}")
    if src.is_dir():
        shutil.copytree(src, dest, dirs_exist_ok=True)
    else:
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dest)


def write_text_file(path: Path, contents: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(contents.rstrip() + "\n")


def generation_metadata(spec: RepoSpec, source_ref: str, source_sha: str) -> str:
    generated_at = dt.datetime.now(dt.timezone.utc).isoformat()
    return f"""# Generated Repository

This repository is a generated EasyMANET public product surface.

- Product key: `{spec.key}`
- Public repo: `{spec.name}`
- Authoring repo: `the-Drunken-coder/easymanet`
- Source ref: `{source_ref}`
- Source commit: `{source_sha}`
- Generated at: `{generated_at}`

Normal development should happen in the authoring repo. Changes are published
here by the authoring repo publish process so the public product surfaces do
not drift from the shared EasyMANET model.
"""


def generate_repo(spec: RepoSpec, output_dir: Path, source_ref: str, source_sha: str) -> Path:
    repo_dir = output_dir / spec.name
    if repo_dir.exists():
        shutil.rmtree(repo_dir)
    repo_dir.mkdir(parents=True)

    for rel_path in spec.source_paths:
        copy_source_path(rel_path, repo_dir)

    for rel_path, contents in spec.generated_files.items():
        if rel_path == "REPO_GENERATION.md":
            contents = generation_metadata(spec, source_ref, source_sha)
        write_text_file(repo_dir / rel_path, contents)

    return repo_dir


def github_repo_exists(owner: str, spec: RepoSpec) -> bool:
    result = run(
        ["gh", "repo", "view", f"{owner}/{spec.name}", "--json", "name"],
        env=github_cli_env(),
        check=False,
    )
    return result.returncode == 0


def create_github_repo(owner: str, spec: RepoSpec) -> None:
    run(
        [
            "gh",
            "repo",
            "create",
            f"{owner}/{spec.name}",
            "--public",
            "--description",
            spec.description,
            "--disable-wiki",
            "--clone=false",
        ],
        env=github_cli_env(),
    )


def publish_token() -> str | None:
    return os.environ.get("EASYMANET_PUBLIC_REPO_TOKEN") or os.environ.get("GH_TOKEN")


def github_cli_env() -> dict[str, str] | None:
    token = publish_token()
    if not token:
        return None

    env = os.environ.copy()
    env["GH_TOKEN"] = token
    return env


def remote_url(owner: str, spec: RepoSpec) -> str:
    return f"https://{GITHUB_HOST}/{owner}/{spec.name}.git"


def git_auth_env() -> dict[str, str] | None:
    token = publish_token()
    if not token:
        return None

    env = os.environ.copy()
    try:
        index = int(env.get("GIT_CONFIG_COUNT", "0"))
    except ValueError:
        index = 0
    encoded = base64.b64encode(f"x-access-token:{token}".encode()).decode()
    env["GIT_CONFIG_COUNT"] = str(index + 1)
    env[f"GIT_CONFIG_KEY_{index}"] = f"http.https://{GITHUB_HOST}/.extraheader"
    env[f"GIT_CONFIG_VALUE_{index}"] = f"AUTHORIZATION: basic {encoded}"
    env["GIT_TERMINAL_PROMPT"] = "0"
    return env


def remote_default_branch(owner: str, spec: RepoSpec) -> str:
    result = run(
        ["git", "ls-remote", "--symref", remote_url(owner, spec), "HEAD"],
        env=git_auth_env(),
        check=False,
    )
    if result.returncode != 0:
        return "main"

    for line in result.stdout.splitlines():
        parts = line.split()
        if len(parts) == 3 and parts[0] == "ref:" and parts[2] == "HEAD":
            ref = parts[1]
            if ref.startswith("refs/heads/"):
                return ref.removeprefix("refs/heads/")
    return "main"


def clear_worktree(path: Path) -> None:
    for child in path.iterdir():
        if child.name == ".git":
            continue
        if child.is_dir():
            shutil.rmtree(child)
        else:
            child.unlink()


def checkout_branch(worktree_dir: Path, branch: str) -> None:
    remote_branch = f"origin/{branch}"
    result = run(["git", "rev-parse", "--verify", remote_branch], cwd=worktree_dir, check=False)
    if result.returncode == 0:
        run(["git", "checkout", "-B", branch, remote_branch], cwd=worktree_dir)
    else:
        run(["git", "checkout", "-B", branch], cwd=worktree_dir)


def ensure_worktree(owner: str, spec: RepoSpec, worktree_dir: Path) -> str:
    url = remote_url(owner, spec)
    branch = remote_default_branch(owner, spec)
    auth_env = git_auth_env()
    if (worktree_dir / ".git").exists():
        run(["git", "remote", "set-url", "origin", url], cwd=worktree_dir)
        run(["git", "fetch", "origin"], cwd=worktree_dir, env=auth_env)
        checkout_branch(worktree_dir, branch)
        return branch

    worktree_dir.parent.mkdir(parents=True, exist_ok=True)
    run(["git", "clone", url, str(worktree_dir)], env=auth_env)
    checkout_branch(worktree_dir, branch)
    return branch


def sync_to_remote(owner: str, spec: RepoSpec, generated_dir: Path, output_dir: Path, source_sha: str) -> str | None:
    worktree_dir = output_dir.parent / "product-repo-worktrees" / spec.name
    branch = ensure_worktree(owner, spec, worktree_dir)
    clear_worktree(worktree_dir)
    shutil.copytree(generated_dir, worktree_dir, dirs_exist_ok=True)

    run(["git", "config", "user.name", "EasyMANET Publisher"], cwd=worktree_dir)
    run(["git", "config", "user.email", "easymanet-publisher@users.noreply.github.com"], cwd=worktree_dir)
    run(["git", "add", "-A"], cwd=worktree_dir)

    diff = run(["git", "diff", "--cached", "--quiet"], cwd=worktree_dir, check=False)
    if diff.returncode == 0:
        return None

    run(
        [
            "git",
            "commit",
            "-m",
            f"Publish generated {spec.key} surface",
            "-m",
            f"Source commit: {source_sha}",
        ],
        cwd=worktree_dir,
    )
    run(["git", "push", "origin", branch], cwd=worktree_dir, env=git_auth_env())
    return git_output(["rev-parse", "HEAD"], cwd=worktree_dir)


def dispatch_release(owner: str, spec: RepoSpec, payload: dict[str, str]) -> None:
    run(
        [
            "gh",
            "api",
            "--method",
            "POST",
            f"repos/{owner}/{spec.name}/dispatches",
            "--input",
            "-",
        ],
        env=github_cli_env(),
        input_text=json.dumps({"event_type": spec.dispatch_event, "client_payload": payload}),
    )


def build_payload(args: argparse.Namespace, source_ref: str, source_sha: str) -> dict[str, str]:
    payload = {
        "source_repo": args.source_repo,
        "source_ref": source_ref,
        "source_sha": source_sha,
    }
    if args.release_tag:
        payload["release_tag"] = args.release_tag
    if args.openmanet_version:
        payload["openmanet_version"] = args.openmanet_version
    if args.board:
        payload["board"] = args.board
    if args.target:
        payload["target"] = args.target
    if args.jobs:
        payload["jobs"] = str(args.jobs)
    return payload


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--product", choices=["all", *REPO_SPECS.keys()], default="all")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--remote-owner", default=DEFAULT_OWNER)
    parser.add_argument("--source-repo", default="the-Drunken-coder/easymanet")
    parser.add_argument("--source-ref", default=os.environ.get("GITHUB_REF_NAME", ""))
    parser.add_argument("--source-sha", default=os.environ.get("GITHUB_SHA", ""))
    parser.add_argument("--create-missing", action="store_true")
    parser.add_argument("--push", action="store_true")
    parser.add_argument("--dispatch", action="store_true")
    parser.add_argument("--release-tag", default="")
    parser.add_argument("--openmanet-version", default="1.6.5")
    parser.add_argument("--board", default="ekh-bcm2711")
    parser.add_argument("--target", default="rpi4-mm6108-spi")
    parser.add_argument("--jobs", default="2")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    source_ref = args.source_ref or git_output(["branch", "--show-current"]) or "unknown"
    source_sha = args.source_sha or git_output(["rev-parse", "HEAD"])
    args.output_dir.mkdir(parents=True, exist_ok=True)

    payload = build_payload(args, source_ref, source_sha)
    for spec in selected_specs(args.product):
        generated_dir = generate_repo(spec, args.output_dir, source_ref, source_sha)
        print(f"generated {spec.name}: {generated_dir}")

        if args.create_missing and not github_repo_exists(args.remote_owner, spec):
            create_github_repo(args.remote_owner, spec)
            print(f"created {args.remote_owner}/{spec.name}")

        if args.push:
            commit_sha = sync_to_remote(args.remote_owner, spec, generated_dir, args.output_dir, source_sha)
            if commit_sha:
                print(f"pushed {args.remote_owner}/{spec.name}@{commit_sha}")
            else:
                print(f"no changes for {args.remote_owner}/{spec.name}")

        if args.dispatch:
            dispatch_release(args.remote_owner, spec, payload)
            print(f"dispatched {spec.dispatch_event} to {args.remote_owner}/{spec.name}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
