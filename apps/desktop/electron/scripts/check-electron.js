const fs = require("node:fs");
const path = require("node:path");
const os = require("node:os");
const { spawnSync } = require("node:child_process");
const { hasTraversalSegment, resolveConfigPath } = require("../path-utils");

const repoRoot = path.resolve(__dirname, "../../../..");
const files = [
  path.join(repoRoot, "apps/desktop/electron/main.js"),
  path.join(repoRoot, "apps/desktop/electron/path-utils.js"),
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
const bridgeEnv = {
  ...process.env,
  EASYMANET_WORKSPACE: workspace,
  PYTHONPATH: [
    path.join(repoRoot, "packages/core/src"),
    path.join(repoRoot, "apps/desktop/src"),
    process.env.PYTHONPATH || "",
  ].filter(Boolean).join(path.delimiter),
};
const bridge = spawnBridge(["state"]);

if (bridge.status !== 0) {
  cleanupWorkspace();
  console.error(bridge.stderr || bridge.stdout);
  process.exit(bridge.status || 1);
}

let payload;
try {
  payload = JSON.parse(bridge.stdout);
} catch (error) {
  cleanupWorkspace();
  console.error(`Could not parse EasyMANET bridge JSON: ${error.message}`);
  console.error(bridge.stdout);
  process.exit(1);
}
if (!payload.ok) {
  cleanupWorkspace();
  console.error(bridge.stdout);
  process.exit(1);
}

const fleetPath = path.join(workspace, "Fleets", "field.yml");
fs.mkdirSync(path.dirname(fleetPath), { recursive: true });
fs.copyFileSync(path.join(repoRoot, "examples", "three-node-field-mesh.yml"), fleetPath);
const expectedFleetPath = fs.realpathSync(fleetPath);

if (!hasTraversalSegment("../field")) {
  cleanupWorkspace();
  console.error("Traversal segment check did not reject ../field");
  process.exit(1);
}

resolveConfigPath("../field", { runBridge: runBridgeJson, homeDir: () => os.homedir() })
  .then((traversal) => {
    if (traversal.ok || !String((traversal.errors || [])[0] || "").includes("inside the Fleets folder")) {
      throw new Error(`Traversal config unexpectedly resolved: ${JSON.stringify(traversal)}`);
    }
    return resolveConfigPath("field", { runBridge: runBridgeJson, homeDir: () => os.homedir() });
  })
  .then((resolved) => {
    if (!resolved.ok || !samePath(resolved.config, expectedFleetPath)) {
      throw new Error(
        `Relative fleet name did not resolve through bridge: ${JSON.stringify({
          resolved,
          expected: expectedFleetPath,
        })}`,
      );
    }
    cleanupWorkspace();
    console.log("Electron desktop files and EasyMANET bridge are valid.");
  })
  .catch((error) => {
    cleanupWorkspace();
    console.error(error.message);
    process.exit(1);
  });

function spawnBridge(args) {
  return spawnSync(python, ["-m", "easymanet_desktop.bridge", ...args], {
    cwd: repoRoot,
    env: bridgeEnv,
    encoding: "utf8",
  });
}

function runBridgeJson(args) {
  const result = spawnBridge(args);
  if (result.status !== 0) {
    return { ok: false, errors: [result.stderr || result.stdout || `bridge exited ${result.status}`] };
  }
  try {
    return JSON.parse(result.stdout);
  } catch (error) {
    return { ok: false, errors: [`Could not parse bridge JSON: ${error.message}`], raw: result.stdout };
  }
}

function cleanupWorkspace() {
  if (typeof fs.rmSync === "function") {
    fs.rmSync(workspace, { recursive: true, force: true });
    return;
  }
  fs.rmdirSync(workspace, { recursive: true });
}

function samePath(left, right) {
  const normalize = (value) => {
    const resolved = path.resolve(String(value || ""));
    try {
      return fs.realpathSync(resolved);
    } catch (_error) {
      return resolved;
    }
  };
  const leftPath = normalize(left);
  const rightPath = normalize(right);
  if (process.platform === "win32") {
    return leftPath.toLowerCase() === rightPath.toLowerCase();
  }
  return leftPath === rightPath;
}

function venvPython(venvRoot) {
  const binDir = process.platform === "win32" ? "Scripts" : "bin";
  const exe = process.platform === "win32" ? "python.exe" : "python";
  return path.join(venvRoot, binDir, exe);
}
