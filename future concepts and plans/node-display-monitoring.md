# Node display monitoring

## Concept

Each mesh node can drive a local monitoring UI on an attached HDMI display. The experience should feel like plugging a monitor into a powered-on Pi: after a short boot delay, the screen shows live status without any on-device login or setup.

The UI is not the primary configuration path (fleet config and provisioning stay file-driven). The display is for field visibility—what the node is doing right now, and eventually how it relates to the rest of the mesh.

## Priorities

### Plug-and-watch

- Power on the Pi; plug in a display; monitoring UI appears on its own.
- No keyboard, no touch login, no browser on another machine required for the basic case.
- A startup delay is acceptable; an interactive setup step on the display is not.

### Live, not static

- Content refreshes on a timer or as state changes—not a one-shot splash screen.
- Early versions can be simple (text and counters). The architecture should allow richer layouts later without redefining the product.

### Room to grow visually

- Future iterations may include small diagrams (topology sketches, link state, role indicators)—lightweight graphics, not a full desktop or heavy UI framework.
- Start minimal; add meaning and visuals as mesh observability matures.

## Non-goals (for now)

- Replacing remote admin (SSH, web UI, fleet tooling).
- Requiring a specific monitor resolution or input device.
- Defining exact metrics, screens, or implementation layout in this document.

## Open questions

- What belongs on screen at boot vs after mesh is up?
- How much fleet context (intended topology) vs node-local view (neighbors, link quality)?
- Headless operation: display optional; no impact when nothing is plugged in.
