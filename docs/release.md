# Release Checklist

EasyMANET `0.1.0` is the first clean monorepo release. It ships the CLI,
image tooling, Electron desktop shell, shared Documents workspace, and local
publish/export tooling as one coordinated product.

## Version Policy

- `0.1.0` is the first release of the new monorepo shape.
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
  tools/publish/src/easymanet_publish/templates/*/.github/workflows/*.yml

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

## Tag And Publish

Only tag after every verification item above passes:

```bash
git tag -a v0.1.0 -m "EasyMANET v0.1.0"
```

Publish the wheel, Electron artifact, image artifacts, and
`easymanet-image-release.json` together. Keep the tag, Python version, Electron
version, and image release manifest aligned.
