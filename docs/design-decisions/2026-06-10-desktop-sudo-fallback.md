# Desktop Sudo Fallback

## Status

Accepted

## Context

Flashing removable media often requires elevated write access. A packaged
desktop app could install a privileged helper, prompt for credentials in-app, or
hand the operator an explicit terminal command.

## Decision

Do not install a privileged helper. If the bridge detects that write access is
missing, return a copy-paste `sudo` command that re-runs the same bridge flash
operation with resolved image arguments where available.

## Consequences

The app stays local-first and avoids long-lived privileged components. The trade
off is a less polished flash path when privileges are missing, but the operator
can inspect the exact command before running it.
