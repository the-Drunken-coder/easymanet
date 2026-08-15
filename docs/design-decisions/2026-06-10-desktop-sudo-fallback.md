# Desktop Sudo Fallback

## Status

Accepted

## Context

Flashing removable media often requires elevated write access. A packaged
desktop app could install a privileged helper, prompt for credentials in-app, or
hand the operator an explicit terminal command.

## Decision

Do not install a privileged helper. On macOS, the native desktop prompts for an
administrator password and runs the narrow bridge flash command through
`sudo`. If in-app elevation is unavailable, return the same resolved command as
an explicit copyable terminal fallback.

## Consequences

The app stays local-first and avoids long-lived privileged components. Elevated
inputs are staged only for the command lifetime and cleaned after confirmed
process-group exit. If cleanup cannot be confirmed within the bounded shutdown
window, the result records the process-group ID and preserves the stage with a
`cleanup-pending.json` recovery record. The operator still gets an inspectable
terminal command when native elevation cannot run. A preserved stage contains
cleartext fleet secrets on an unencrypted temporary path; remove it after the
privileged flash process has ended.
