#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ASSETS_DIR="$ROOT/assets"
SVG="$ASSETS_DIR/easymanet-icon.svg"
PNG="$ASSETS_DIR/easymanet-icon.png"
ICNS="$ASSETS_DIR/easymanet-icon.icns"
ICONSET="$ASSETS_DIR/easymanet-icon.iconset"

if [[ ! -f "$SVG" ]]; then
  echo "Missing icon source: $SVG" >&2
  exit 1
fi

for tool in swift sips iconutil; do
  if ! command -v "$tool" >/dev/null 2>&1; then
    echo "Missing required macOS icon tool: $tool" >&2
    exit 1
  fi
done

TMP_DIR="$(mktemp -d)"
cleanup() {
  rm -rf "$TMP_DIR" "$ICONSET"
}
trap cleanup EXIT

SWIFT_RENDERER="$TMP_DIR/render-icon.swift"
cat > "$SWIFT_RENDERER" <<'SWIFT'
import AppKit

let svgPath = CommandLine.arguments[1]
let pngPath = CommandLine.arguments[2]
let pixelSize = 1024
let size = NSSize(width: pixelSize, height: pixelSize)

guard let image = NSImage(contentsOfFile: svgPath) else {
  fputs("Could not load SVG: \(svgPath)\n", stderr)
  exit(1)
}

guard let rep = NSBitmapImageRep(
  bitmapDataPlanes: nil,
  pixelsWide: pixelSize,
  pixelsHigh: pixelSize,
  bitsPerSample: 8,
  samplesPerPixel: 4,
  hasAlpha: true,
  isPlanar: false,
  colorSpaceName: .deviceRGB,
  bitmapFormat: [.alphaFirst],
  bytesPerRow: 0,
  bitsPerPixel: 0
) else {
  fputs("Could not create bitmap renderer\n", stderr)
  exit(1)
}

rep.size = size
NSGraphicsContext.saveGraphicsState()
NSGraphicsContext.current = NSGraphicsContext(bitmapImageRep: rep)
NSGraphicsContext.current?.imageInterpolation = .high
NSColor.clear.setFill()
NSRect(origin: .zero, size: size).fill()
image.draw(in: NSRect(origin: .zero, size: size), from: .zero, operation: .copy, fraction: 1.0)
NSGraphicsContext.restoreGraphicsState()

guard let png = rep.representation(using: .png, properties: [:]) else {
  fputs("Could not create PNG representation\n", stderr)
  exit(1)
}

try png.write(to: URL(fileURLWithPath: pngPath))
SWIFT

swift "$SWIFT_RENDERER" "$SVG" "$PNG"

mkdir -p "$ICONSET"
sips -z 16 16 "$PNG" --out "$ICONSET/icon_16x16.png" >/dev/null
sips -z 32 32 "$PNG" --out "$ICONSET/icon_16x16@2x.png" >/dev/null
sips -z 32 32 "$PNG" --out "$ICONSET/icon_32x32.png" >/dev/null
sips -z 64 64 "$PNG" --out "$ICONSET/icon_32x32@2x.png" >/dev/null
sips -z 128 128 "$PNG" --out "$ICONSET/icon_128x128.png" >/dev/null
sips -z 256 256 "$PNG" --out "$ICONSET/icon_128x128@2x.png" >/dev/null
sips -z 256 256 "$PNG" --out "$ICONSET/icon_256x256.png" >/dev/null
sips -z 512 512 "$PNG" --out "$ICONSET/icon_256x256@2x.png" >/dev/null
sips -z 512 512 "$PNG" --out "$ICONSET/icon_512x512.png" >/dev/null
sips -z 1024 1024 "$PNG" --out "$ICONSET/icon_512x512@2x.png" >/dev/null

iconutil -c icns "$ICONSET" -o "$ICNS"

echo "Wrote $PNG"
echo "Wrote $ICNS"
