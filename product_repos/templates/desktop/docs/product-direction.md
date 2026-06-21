# Desktop Product Direction

EasyMANET Desktop is intended to be a local-first operator console. It should
share the CLI's safety model and transparent project files rather than becoming
a separate cloud control plane.

Current first workflows:

- Discover compatible image releases.
- Download and cache images locally.
- Validate fleet configuration.
- Select a fleet node.
- Select a removable disk safely.
- Preview, flash, and eject media through the shared CLI flash path.
- Read boot reports and local diagnostics.
- Run diagnostics, import offline boot reports, copy a support summary, and
  export support bundles from the shared `Diagnostics/` workspace folder.

This generated repo exists now so release and issue-reporting infrastructure can
ship with the actual Electron app sources and packaged desktop release
artifacts.
