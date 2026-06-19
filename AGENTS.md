The role of this file is to describe common mistakes and confusion points that agents might encounter as they work in this project.

If you encounter something surprising, tell the developer and add the lesson here so future agents do not rediscover the same failure.

EasyMANET is a provisioning, imaging, and configuration layer on top of OpenMANET. It is not a new MANET protocol, a cloud dashboard, a monitoring service, a Meshtastic integration, or a drone UI.

The active local desktop beta runs from `/Users/lanearaujo/Documents/EasyMANET/Source/easymanet` and uses `/Users/lanearaujo/Documents/EasyMANET` as the operator workspace. To run, smoke-test, inspect, stop, or fetch logs, use `/Users/lanearaujo/.codex/actions/run-easymanet-local-desktop` instead of inventing a different launch command.

There may be multiple EasyMANET checkouts on this machine. Before PR, release, desktop, or hardware work, confirm the checkout with `pwd`, `git status --short --branch`, and, when needed, `git worktree list`. Do not assume `/Users/lanearaujo/Documents/coding/easymanet` and `/Users/lanearaujo/Documents/EasyMANET/Source/easymanet` are interchangeable.

EasyMANET is authored as a private monorepo. The CLI, desktop app, image builder, shared core, and publish tooling live as separate product surfaces inside this repo; public sub-repos are generated/exported surfaces, not the primary source of truth. Do not treat a public sub-repo export as authoritative unless the task is specifically about release/export behavior.

Keep product-surface claims honest. CLI flash capability, Electron shell capability, Python desktop bridge capability, release publishing, and actual end-user desktop flashing are separate surfaces. Do not call the product "fully functional" because packaging or CLI flows work.

The desktop app reads and writes through the shared workspace, not a private app database. The default workspace is `/Users/lanearaujo/Documents/EasyMANET`; `Fleets/`, `Images/`, `Diagnostics/`, and `Builds/` are operator data, not repo source.
