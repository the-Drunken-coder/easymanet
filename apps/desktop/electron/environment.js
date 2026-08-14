const { app } = require("electron");
const fs = require("node:fs");
const path = require("node:path");
const { repoRoot } = require("./constants");

const privilegedPath = "/usr/bin:/bin:/usr/sbin:/sbin";
const isolatedStageBridge = [
  "import runpy, sys",
  "source_root = sys.argv.pop(1)",
  "sys.path.insert(0, source_root)",
  "runpy.run_module('easymanet_desktop.bridge', run_name='__main__')",
].join("; ");

function elevatedBridgeCommand(args, stage) {
  const bundledBridge = packagedBridgeBinary();
  if (bundledBridge) {
    return {
      command: bundledBridge,
      args,
      cwd: stage?.root || elevatedTempRoot(),
      env: stage ? {EASYMANET_WORKSPACE: stage.workspaceDir} : {},
    };
  }
  if (stage) {
    return {
      command: elevatedPythonPath(),
      args: ["-I", "-c", isolatedStageBridge, stage.sourceRoots[0], ...args],
      cwd: stage.root,
      env: {
        EASYMANET_WORKSPACE: stage.workspaceDir,
      },
    };
  }
  return {
    command: elevatedPythonPath(),
    args: ["-I", "-m", "easymanet_desktop.bridge", ...args],
    cwd: elevatedTempRoot(),
    env: {},
  };
}

function sudoBridgeCommand(bridge) {
  if (!path.isAbsolute(bridge.command)) {
    throw new Error(`Elevated bridge command must be an absolute path: ${bridge.command}`);
  }
  const envParts = Object.entries(elevatedBridgeEnv(bridge.env || {}))
    .filter(([, value]) => value)
    .map(([key, value]) => `${key}=${value}`);
  return {
    command: "/usr/bin/sudo",
    args: [
      "-S",
      "-p",
      "",
      "--",
      "/usr/bin/env",
      ...envParts,
      bridge.command,
      ...bridge.args,
    ],
  };
}

function elevatedBridgeEnv(extraEnv = {}) {
  const result = {
    HOME: app.getPath("home"),
    PATH: privilegedPath,
    EASYMANET_SKIP_UPDATE_CHECK: "1",
    PYTHONDONTWRITEBYTECODE: "1",
    PYTHONNOUSERSITE: "1",
  };
  if (extraEnv.EASYMANET_WORKSPACE) {
    result.EASYMANET_WORKSPACE = extraEnv.EASYMANET_WORKSPACE;
  }
  return result;
}

function elevatedPythonPath() {
  const projectPython = venvPython(path.join(repoRoot, ".codex-venv"));
  for (const candidate of [
    projectPython,
    "/opt/homebrew/opt/python@3.14/bin/python3.14",
    "/opt/homebrew/bin/python3.14",
    "/opt/homebrew/bin/python3",
    "/usr/local/bin/python3.14",
    "/usr/local/bin/python3",
    "/usr/bin/python3",
  ]) {
    if (path.isAbsolute(candidate) && isExecutableFile(candidate)) {
      return candidate;
    }
  }
  throw new Error("No fixed Python interpreter is available for elevated flashing");
}

function isExecutableFile(candidate) {
  try {
    const stat = fs.statSync(candidate);
    fs.accessSync(candidate, fs.constants.X_OK);
    return stat.isFile();
  } catch (_error) {
    return false;
  }
}

function elevatedTempRoot() {
  return "/tmp";
}

function pythonPath() {
  if (process.env.EASYMANET_PYTHON) {
    return process.env.EASYMANET_PYTHON;
  }
  if (process.env.VIRTUAL_ENV) {
    return venvPython(process.env.VIRTUAL_ENV);
  }
  const localVenv = venvPython(path.join(repoRoot, ".codex-venv"));
  if (fs.existsSync(localVenv)) {
    return localVenv;
  }
  return process.platform === "win32" ? "python" : "python3";
}

function venvPython(venvRoot) {
  const binDir = process.platform === "win32" ? "Scripts" : "bin";
  const exe = process.platform === "win32" ? "python.exe" : "python";
  return path.join(venvRoot, binDir, exe);
}

function bridgeEnv() {
  if (app.isPackaged) {
    return { ...process.env };
  }
  const sourceRoots = process.env.EASYMANET_ELECTRON_NO_SOURCE_PATHS === "1" ? [] : [
    path.join(repoRoot, "packages", "core", "src"),
    path.join(repoRoot, "apps", "desktop", "src"),
  ];
  const existing = process.env.PYTHONPATH ? process.env.PYTHONPATH.split(path.delimiter) : [];
  return {
    ...process.env,
    PYTHONPATH: [...sourceRoots, ...existing].join(path.delimiter),
  };
}

function indexHtmlPath() {
  return path.join(staticRoot(), "index.html");
}

function staticRoot() {
  if (app.isPackaged) {
    return path.join(process.resourcesPath, "desktop-static");
  }
  return path.join(repoRoot, "apps", "desktop", "src", "easymanet_desktop", "static");
}

function bridgeCommand(args) {
  const overrideBridge = testingBridgeOverride();
  if (overrideBridge) {
    return { command: overrideBridge, args };
  }
  const bundledBridge = packagedBridgeBinary();
  if (bundledBridge) {
    return { command: bundledBridge, args };
  }
  return {
    command: pythonPath(),
    args: ["-m", "easymanet_desktop.bridge", ...args],
  };
}

function testingBridgeOverride() {
  const overrideBridge = process.env.EASYMANET_BRIDGE_BIN || "";
  if (!overrideBridge) {
    return "";
  }
  // EASYMANET_BRIDGE_BIN is a development/testing override; packaged apps use the bundled bridge by default.
  if (app.isPackaged && process.env.EASYMANET_ELECTRON_ALLOW_BRIDGE_OVERRIDE !== "1") {
    console.warn("Ignoring EASYMANET_BRIDGE_BIN in a packaged app.");
    return "";
  }
  validateExecutableOverride(overrideBridge, "EASYMANET_BRIDGE_BIN");
  return overrideBridge;
}

function validateExecutableOverride(filePath, label) {
  if (!path.isAbsolute(filePath)) {
    throw new Error(`${label} must be an absolute path`);
  }
  try {
    const stat = fs.statSync(filePath);
    if (!stat.isFile()) {
      throw new Error("path is not a file");
    }
    const accessMode = process.platform === "win32" ? fs.constants.R_OK : fs.constants.X_OK;
    fs.accessSync(filePath, accessMode);
  } catch (error) {
    throw new Error(`${label} must point to an executable file: ${filePath} (${error.message})`);
  }
}

function packagedBridgeBinary() {
  if (!app.isPackaged) {
    return "";
  }
  const binary = path.join(
    process.resourcesPath,
    "backend",
    "easymanet-bridge",
    process.platform === "win32" ? "easymanet-bridge.exe" : "easymanet-bridge"
  );
  return fs.existsSync(binary) ? binary : "";
}

function bridgeWorkingDirectory() {
  return app.isPackaged ? app.getPath("userData") : repoRoot;
}

module.exports = {
  bridgeCommand,
  bridgeEnv,
  bridgeWorkingDirectory,
  elevatedBridgeCommand,
  elevatedBridgeEnv,
  elevatedPythonPath,
  elevatedTempRoot,
  indexHtmlPath,
  packagedBridgeBinary,
  pythonPath,
  staticRoot,
  sudoBridgeCommand,
  testingBridgeOverride,
  validateExecutableOverride,
  venvPython,
};
