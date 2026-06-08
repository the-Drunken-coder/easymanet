# Desktop Product Direction

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
