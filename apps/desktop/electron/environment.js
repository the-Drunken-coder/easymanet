const { app } = require("electron");
const fs = require("node:fs");
const path = require("node:path");
const { repoRoot } = require("./constants");

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
      args: ["-m", "easymanet_desktop.bridge", ...args],
      cwd: stage.root,
      env: {
        PYTHONPATH: stage.sourceRoots.join(path.delimiter),
        EASYMANET_WORKSPACE: stage.workspaceDir,
      },
    };
  }
  return bridgeCommand(args);
}

function sudoBridgeCommand(bridge) {
  const envParts = Object.entries(elevatedBridgeEnv(bridge.env || {}))
    .filter(([, value]) => value)
    .map(([key, value]) => `${key}=${value}`);
  return {
    command: "sudo",
    args: [
      "-S",
      "-p",
      "",
      "--",
    "env",
    ...envParts,
      bridge.command,
      ...bridge.args,
    ],
  };
}

function elevatedBridgeEnv(extraEnv = {}) {
  const env = bridgeEnv();
  const result = {
    HOME: app.getPath("home"),
    PATH: env.PATH || process.env.PATH || "/usr/bin:/bin:/usr/sbin:/sbin",
    EASYMANET_SKIP_UPDATE_CHECK: env.EASYMANET_SKIP_UPDATE_CHECK || "1",
    PYTHONDONTWRITEBYTECODE: "1",
    ...extraEnv,
  };
  for (const key of [
    "EASYMANET_WORKSPACE",
    "EASYMANET_PYTHON",
    "VIRTUAL_ENV",
    "EASYMANET_BRIDGE_BIN",
    "EASYMANET_ELECTRON_ALLOW_BRIDGE_OVERRIDE",
    "EASYMANET_ELECTRON_NO_SOURCE_PATHS",
  ]) {
    if (env[key] && !(key in result)) {
      result[key] = env[key];
    }
  }
  return result;
}

function elevatedPythonPath() {
  const configured = configuredPythonPath();
  if (configured && usablePythonCandidate(configured)) {
    return configured;
  }
  for (const candidate of [
    "/opt/homebrew/opt/python@3.14/bin/python3.14",
    "/opt/homebrew/bin/python3.14",
    "/opt/homebrew/bin/python3",
    "/usr/local/bin/python3.14",
    "/usr/local/bin/python3",
  ]) {
    if (fs.existsSync(candidate)) {
      return candidate;
    }
  }
  const current = pythonPath();
  if (!isInsideDocuments(current)) {
    return current;
  }
  return process.platform === "win32" ? "python" : "python3";
}

function configuredPythonPath() {
  if (process.env.EASYMANET_PYTHON) {
    return process.env.EASYMANET_PYTHON;
  }
  if (process.env.VIRTUAL_ENV) {
    return venvPython(process.env.VIRTUAL_ENV);
  }
  return "";
}

function usablePythonCandidate(candidate) {
  return path.isAbsolute(candidate) ? fs.existsSync(candidate) : true;
}

function isInsideDocuments(value) {
  const documents = path.resolve(app.getPath("home"), "Documents");
  const candidate = path.resolve(value);
  return candidate === documents || candidate.startsWith(documents + path.sep);
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
