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
python tools/verify.py fast
python tools/verify.py openwrt-sim
python tools/verify.py package
python tools/verify.py artifact
actionlint .github/workflows/*.yml product_repos/templates/*/.github/workflows/*.yml
```

Install `actionlint` from a package manager or the upstream release artifact
before the release check. Do not rely on `go run` during release verification;
it adds module-cache and network state to a check that should be repeatable.

`fast` runs the Python tests, overlay shell syntax, Electron shell check,
overlay packaging check, and whitespace diff check. `openwrt-sim` runs the
targeted first-boot, provisioning, API, status, and LED behavior tests.
`package` installs Electron dependencies with `npm ci`, builds a wheel, installs
it into a temporary venv, validates the sample fleet through the installed
`easymanet` command, verifies removed import paths stay removed, runs the
installed-wheel Electron smoke, and uses clean temporary Python environments so
host packaging state does not leak into the release check. `artifact` runs the
non-hardware source, synthetic boot-payload, and read-only image-cache checks;
pass a built image and release manifest to the same profile after image build.

For firmware, flashing, provisioning, radio, or release-candidate image changes,
run the manual hardware-in-the-loop gate against a real gate/point pair after
the non-hardware checks pass. This is a scheduled, nightly, or release-only gate,
not a per-PR requirement:

```bash
.codex-venv/bin/python tools/verify.py hil \
  --config examples/three-node-field-mesh.yml \
  --gate-node gate01 \
  --point-node point01 \
  --gate-device /dev/disk4 \
  --point-device /dev/disk5 \
  --point-ssh-enabled \
  --base-image dist/release/images/openmanet-1.6.5-rpi4-mm6108-spi-squashfs-sysupgrade.img.gz \
  --image-sha256 <sha256> \
  --allow-flash \
  --yes
```

To reuse already-flashed nodes, omit `--gate-device` and `--point-device`; pass
`--gate-ip` or `--point-ip` only when the fleet IPs are not the active probe
addresses. Flashing never auto-selects disks and will not write media unless a
device, `--allow-flash`, and `--yes` are all present. The runner waits 90-120
seconds after the operator confirms that flashed media is inserted and the nodes
are booting, probes the node API, checks SSH where enabled, verifies mesh
visibility and support codes, checks boot-report availability, optionally runs
iperf3 throughput smoke, and writes both JSON evidence and a redacted support
bundle to the shared `Diagnostics/` workspace. Use `--skip-boot-prompt` only for
lab fixtures where flashed media is automatically booted before probing.

Flashed media is sensitive until first boot completes: `provision.json` is
written in cleartext on the boot volume until provisioning succeeds, and the
overlay copy at `/etc/easymanet/provision.json` remains mode `0600`.

Point nodes normally have SSH disabled. For a release HIL run that keeps point
SSH disabled, pass `--point-boot-report /path/to/boot` or a
`boot-report-latest` directory so boot-report availability can still be proven.

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
IMAGE=dist/release/images/openmanet-1.6.5-rpi4-mm6108-spi-squashfs-sysupgrade.img.gz
easymanet image manifest \
  --image "$IMAGE" \
  --output-dir dist/release/images

.codex-venv/bin/python tools/verify.py artifact \
  --artifact "$IMAGE" \
  --release-manifest dist/release/images/easymanet-image-release.json
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

The image release workflow generates release notes with OpenCode Go when the
public image repository has an `OPENCODE_GO_API_KEY` secret. `OPENCODE_API_KEY`
is also accepted for teams that keep one OpenCode key name across tools. The
default OpenCode Go model is `deepseek-v4-flash`; override it with an
`OPENCODE_GO_RELEASE_NOTES_MODEL` variable.

The workflow still supports the older OpenAI path as a fallback when
`OPENAI_API_KEY` is configured instead. If no AI key is configured, release
publishing continues with static fallback notes.

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
try:
    import tomllib
except ModuleNotFoundError:
    import tomli as tomllib

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
