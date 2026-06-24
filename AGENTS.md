# EasyMANET Agent Guidance

Prefer simple, elegant solutions over complex ones.

The role of this file is to describe common mistakes and confusion points that agents might encounter as they work in this project.

If you encounter something surprising, tell the developer and add the lesson here so future agents do not rediscover the same failure.

EasyMANET is a provisioning, imaging, and configuration layer on top of OpenMANET. It is not a new MANET protocol, a cloud dashboard, a monitoring service, a Meshtastic integration, or a drone UI.

The active local desktop beta usually runs from the EasyMANET source checkout under the operator workspace, such as `$EASYMANET_WORKSPACE/Source/easymanet` or `~/Documents/EasyMANET/Source/easymanet` by default. To run, smoke-test, inspect, stop, or fetch logs in a local Codex setup, use `$HOME/.codex/actions/run-easymanet-local-desktop`. If that helper is missing, check `~/.codex/actions/` or ask the developer before inventing a different launch command.

There may be multiple EasyMANET checkouts on this machine. Before PR, release, desktop, or hardware work, confirm the checkout with `pwd`, `git status --short --branch`, and, when needed, `git worktree list`. Do not assume a development checkout, a release/imaging checkout, and a workspace checkout are interchangeable without verifying their paths and git states.

EasyMANET is authored as a private monorepo. The CLI, desktop app, image builder, shared core, and publish tooling live as separate product surfaces inside this repo; public sub-repos are generated/exported surfaces, not the primary source of truth. Use `docs/monorepo.md` as the canonical layout and ownership reference. Treat product planning docs as historical context when they conflict with `docs/monorepo.md`, the README, tests, or publish tooling. Do not treat a public sub-repo export as authoritative unless the task is specifically about release/export behavior.

Keep product-surface claims honest. CLI flash capability, Electron shell capability, Python desktop bridge capability, release publishing, and actual end-user desktop flashing are separate surfaces. Report readiness per surface instead of calling the product "fully functional" because packaging or CLI flows work.

Before claiming a change is ready, run validation relevant to the touched surface. Normal Python changes should pass `pytest -q`. OpenMANET overlay script changes should also pass `sh -n` on the changed files under `images/openmanet/provisioning/openwrt-overlay/`. Electron shell changes should pass `npm --prefix apps/desktop/electron run check`. Release work should include the release checklist in `docs/release.md`.

The desktop app reads and writes through the shared workspace, not a private app database. The default workspace is `~/Documents/EasyMANET`, configurable with `EASYMANET_WORKSPACE`; `Fleets/`, `Images/`, `Diagnostics/`, and `Builds/` are operator data, not repo source.

When checking whether a desktop image cache is current, trust the desktop state payload and `Images/version.json` over a CLI flash dry-run placeholder. The dry-run path can still print `<auto-download for rpi4-mm6108-spi>` even when a verified official image is already cached, because it does not resolve the latest release SHA before planning.
