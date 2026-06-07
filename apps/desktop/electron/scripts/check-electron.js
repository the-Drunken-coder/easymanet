const fs = require("node:fs");
const path = require("node:path");
const os = require("node:os");
const { spawnSync } = require("node:child_process");

const repoRoot = path.resolve(__dirname, "../../../..");
const files = [
  path.join(repoRoot, "apps/desktop/electron/main.js"),
  path.join(repoRoot, "apps/desktop/electron/preload.js"),
  path.join(repoRoot, "apps/desktop/src/easymanet_desktop/static/index.html"),
  path.join(repoRoot, "apps/desktop/src/easymanet_desktop/static/app.js"),
  path.join(repoRoot, "apps/desktop/src/easymanet_desktop/static/styles.css"),
];

for (const file of files) {
  if (!fs.existsSync(file)) {
    console.error(`Missing required Electron file: ${file}`);
    process.exit(1);
  }
}

const localPython = venvPython(path.join(repoRoot, ".codex-venv"));
const fallbackPython = process.platform === "win32" ? "python" : "python3";
const python = process.env.EASYMANET_PYTHON || (fs.existsSync(localPython) ? localPython : fallbackPython);
const workspace = fs.mkdtempSync(path.join(os.tmpdir(), "easymanet-electron-check-"));
const bridge = spawnSync(python, ["-m", "easymanet_desktop.bridge", "state"], {
  cwd: repoRoot,
  env: {
    ...process.env,
    EASYMANET_WORKSPACE: workspace,
    PYTHONPATH: [
      path.join(repoRoot, "packages/core/src"),
      path.join(repoRoot, "packages/image/src"),
      path.join(repoRoot, "apps/cli/src"),
      path.join(repoRoot, "apps/desktop/src"),
      path.join(repoRoot, "tools/publish/src"),
      process.env.PYTHONPATH || "",
    ].filter(Boolean).join(path.delimiter),
  },
  encoding: "utf8",
});

if (bridge.status !== 0) {
  cleanupWorkspace();
  console.error(bridge.stderr || bridge.stdout);
  process.exit(bridge.status || 1);
}

const payload = JSON.parse(bridge.stdout);
if (!payload.ok) {
  cleanupWorkspace();
  console.error(bridge.stdout);
  process.exit(1);
}

cleanupWorkspace();
console.log("Electron desktop files and EasyMANET bridge are valid.");

function cleanupWorkspace() {
  fs.rmSync(workspace, { recursive: true, force: true });
}

function venvPython(venvRoot) {
  const binDir = process.platform === "win32" ? "Scripts" : "bin";
  const exe = process.platform === "win32" ? "python.exe" : "python";
  return path.join(venvRoot, binDir, exe);
}
