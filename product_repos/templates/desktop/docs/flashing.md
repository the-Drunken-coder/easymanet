# Desktop Flashing

The generated EasyMANET Desktop repository contains the local Electron operator
console, its Python bridge, and the shared core code needed by that desktop
surface. It does not expose the `easymanet` CLI command, the OpenMANET image
builder, or the firmware overlay source tree.

Use the desktop app's flash workflow for desktop releases:

1. Open the app.
2. Select a fleet file from the shared EasyMANET workspace.
3. Select the node to provision.
4. Select the removable target disk.
5. Preview the flash plan.
6. Authenticate when prompted and start the flash.

The desktop workflow follows the same disk-safety model as the CLI: it does not
auto-select a disk, requires an explicit operator choice, validates the selected
fleet/node, previews the plan, and stages the node-specific boot payload before
ejecting the media.

SSH enable/disable is chosen at flash time rather than stored in `fleet.yml`.
When no explicit SSH choice is made, first boot uses the role default: gate nodes
enable SSH and point nodes leave SSH disabled.

For command-line flashing, image builds, release manifests, or firmware overlay
development, use the authoring repository or the generated `easymanet-cli` and
`easymanet-images` product repositories instead of this desktop-only surface.
