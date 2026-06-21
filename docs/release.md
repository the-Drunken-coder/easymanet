# Release Checklist

The EasyMANET `0.2.x` release line ships the CLI, image tooling, Electron
desktop flash workflow, shared Documents workspace, and local publish/export
tooling as one coordinated product.

## Version Policy

- `0.2.0` is the first release with desktop flash preview/execution support.
- Python package metadata in `pyproject.toml` and Electron metadata in
  `apps/desktop/electron/package.json` must stay on the same release version.
- The old Python module paths are intentionally not supported:
  `easymanet.cli`, `easymanet.cli_image`, `easymanet.build`,
  `easymanet.cli_flash`, and `easymanet.cli_common` must remain removed.
- Patch releases fix packaging, docs, desktop shell, and provisioning bugs
  without changing accepted fleet config shape.
- Minor releases can add new hardware targets, fleet config fields, desktop
  workflows, or image-discovery behavior.

## Pre-Release Verification

Run these from the repo root:

```bash
EASYMANET_WORKSPACE=/tmp/easymanet-release-tests \
  COVERAGE_FILE=/tmp/easymanet-release.coverage \
  .codex-venv/bin/python -m pytest -q \
  --cov=easymanet --cov-report=term-missing --cov-fail-under=50

npm --prefix apps/desktop/electron ci
npm --prefix apps/desktop/electron run check

go run github.com/rhysd/actionlint/cmd/actionlint@v1.7.11 \
  .github/workflows/*.yml \
  product_repos/templates/*/.github/workflows/*.yml

git diff --check
```

Run the installed-wheel smoke. This builds a wheel, installs it into a
temporary venv, validates the sample fleet through the installed `easymanet`
command, verifies removed import paths stay removed, and runs the Electron
smoke against that installed Python package:

```bash
.codex-venv/bin/python tools/release_smoke.py
```

For a faster local packaging check that skips Electron but still uses an
isolated temporary venv:

```bash
.codex-venv/bin/python tools/release_smoke.py --skip-electron
```

## Build Artifacts

```bash
rm -rf dist/release
mkdir -p dist/release/wheels

.codex-venv/bin/python -m pip wheel \
  --no-deps --no-build-isolation \
  --wheel-dir dist/release/wheels .

npm --prefix apps/desktop/electron ci
npm --prefix apps/desktop/electron run check
```

If a firmware image is part of the release, build it and write the release
manifest next to the image. OpenMANET image filenames carry the OpenMANET
firmware version, which is independent of the EasyMANET package version:

```bash
easymanet image build --output-dir dist/release/images
easymanet image manifest \
  --image dist/release/images/openmanet-1.6.5-rpi4-mm6108-spi-squashfs-sysupgrade.img.gz \
  --output-dir dist/release/images
```

## Image Trust And Channels

Public image releases use two channels:

- `stable`: tags like `images-v<version>`
- `candidate`: tags like `images-v<version>-candidate.1`

Official EasyMANET image auto-downloads require a verified schema-v2
`easymanet-image-release.json`, SHA-256 checksum, GitHub artifact attestation,
and Sigstore/cosign signature bundle. Custom local images and custom URLs are
still allowed with an explicit SHA-256, but they are treated as
checksum-only/user-supplied rather than official.

The image release workflow generates release notes with the OpenAI Responses
API. Configure the public image repository with an `OPENAI_API_KEY` secret and,
optionally, an `OPENAI_RELEASE_NOTES_MODEL` variable. The default model is
`gpt-5.4-mini`.

Retention is automatic after a successful image release:

- keep the latest 5 stable image releases,
- delete candidate releases once they fall outside the latest 3 for their
  target or become older than 90 days,
- never delete the just-published release.

## Diagnostics And Support

Support bundles are exported as redacted `.zip` files from
`easymanet diagnostics bundle` or the desktop app. They include fleet
validation, workspace state, image trust/cache metadata, optional boot reports,
optional disk inventory, and redaction notes.

## Tag And Publish

Only tag after every verification item above passes:

```bash
VERSION=$(.codex-venv/bin/python - <<'PY'
import tomllib
from pathlib import Path

print(tomllib.loads(Path("pyproject.toml").read_text())["project"]["version"])
PY
)
git tag -a "v${VERSION}" -m "EasyMANET v${VERSION}"
```

Publish the wheel, Electron artifact, image artifacts, checksum files,
`easymanet-image-release.json`, signature bundle, attestations, and release
notes together. Each image artifact `NAME.img.gz` must have a sibling
`NAME.img.gz.sha256` file containing one `sha256sum`-style line:
`<hex sha256>  NAME.img.gz`. Keep the tag, Python version, Electron version,
and image release manifest aligned.
