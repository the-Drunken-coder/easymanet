const { app, BrowserWindow, clipboard, dialog, ipcMain, shell } = require("electron");
const { spawn } = require("node:child_process");
const path = require("node:path");
const fs = require("node:fs");

const repoRoot = path.resolve(__dirname, "../../..");
const fleetExtensions = new Set([".yml", ".yaml"]);
const nodeNamePattern = /^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$/;
const bridgeTimeoutMs = 15000;
const flashBridgeTimeoutMs = 30 * 60 * 1000;
const sshModes = new Set(["default", "enable", "disable"]);

function createWindow() {
  const win = new BrowserWindow({
    width: 1180,
    height: 780,
    minWidth: 760,
    minHeight: 560,
    title: "EasyMANET",
    backgroundColor: "#f6f7f4",
    webPreferences: {
      contextIsolation: true,
      nodeIntegration: false,
      preload: path.join(__dirname, "preload.js"),
    },
  });

  win.setMenuBarVisibility(false);
  win.webContents.setWindowOpenHandler(({ url }) => {
    if (url.startsWith("https://")) {
      shell.openExternal(url);
    }
    return { action: "deny" };
  });
  if (process.env.EASYMANET_ELECTRON_SMOKE === "1") {
    win.webContents.once("did-finish-load", async () => {
      const state = await win.webContents.executeJavaScript(`
        (async () => {
          await new Promise((resolve) => {
            const deadline = Date.now() + 5000;
            const tick = () => {
              if (document.querySelector("#workspace-path")?.textContent || Date.now() > deadline) {
                resolve();
                return;
              }
              setTimeout(tick, 50);
            };
            tick();
          });
          return JSON.stringify({
            title: document.title,
            protocol: window.location.protocol,
            hasNativeApi: Boolean(window.easymanet),
            headings: Array.from(document.querySelectorAll("h1,h2")).map((el) => el.textContent.trim()),
            workspace: document.querySelector("#workspace-path")?.textContent || "",
            selectedFleet: document.querySelector("#fleet-select")?.selectedOptions?.[0]?.textContent || "",
            configPath: document.querySelector("#config-path")?.value || "",
            emptyFleetVisible: !document.querySelector("#fleet-empty")?.hidden,
            openFleetsFolderVisible: !document.querySelector("#open-fleets-folder")?.hidden,
            hasFlashControls: Boolean(document.querySelector("#flash-panel"))
          });
        })()
      `);
      console.log(state);
      app.quit();
    });
  }
  win.loadFile(indexHtmlPath());
}

app.whenReady().then(() => {
  registerIpc();
  createWindow();

  app.on("activate", () => {
    if (BrowserWindow.getAllWindows().length === 0) {
      createWindow();
    }
  });
});

app.on("window-all-closed", () => {
  if (process.platform !== "darwin") {
    app.quit();
  }
});

function registerIpc() {
  ipcMain.handle("easymanet:state", () => runBridge(["state"]));
  ipcMain.handle("easymanet:disks", (_event, payload = {}) => {
    const args = ["disks"];
    if (payload.includeAll) {
      args.push("--all");
    }
    return runBridge(args);
  });
  ipcMain.handle("easymanet:validate", async (_event, payload = {}) => {
    const validated = await validatePayload(payload);
    if (!validated.ok) {
      return validated;
    }
    const args = ["validate", "--config", validated.config];
    if (validated.node) {
      args.push("--node", validated.node);
    }
    return runBridge(args);
  });
  ipcMain.handle("easymanet:flash-plan", async (_event, payload = {}) => {
    const validated = await validateFlashPayload(payload);
    if (!validated.ok) {
      return validated;
    }
    return runBridge(["flash-plan", ...flashArgs(validated)], { timeoutMs: flashBridgeTimeoutMs });
  });
  ipcMain.handle("easymanet:flash", async (_event, payload = {}) => {
    const validated = await validateFlashPayload(payload);
    if (!validated.ok) {
      return validated;
    }
    const confirmed = await dialog.showMessageBox({
      type: "warning",
      buttons: ["Flash", "Cancel"],
      defaultId: 1,
      cancelId: 1,
      title: "Flash removable media",
      message: `Flash ${validated.device} for ${validated.node}?`,
      detail: "This writes an OpenMANET image to the selected disk and erases existing data on that disk.",
      noLink: true,
    });
    if (confirmed.response !== 0) {
      return { ok: false, canceled: true, errors: ["Flash canceled"] };
    }
    return runBridge(["flash", ...flashArgs(validated), "--yes"], { timeoutMs: flashBridgeTimeoutMs });
  });
  ipcMain.handle("easymanet:copy-text", (_event, payload = {}) => {
    const text = typeof payload.text === "string" ? payload.text : "";
    if (!text) {
      return { ok: false, errors: ["Nothing to copy"] };
    }
    clipboard.writeText(text);
    return { ok: true };
  });
  ipcMain.handle("easymanet:choose-config", async () => {
    const state = await runBridge(["state"]);
    const defaultPath = state.ok && state.workspace ? state.workspace.fleets_dir : undefined;
    const result = await dialog.showOpenDialog({
      title: "Choose fleet config",
      defaultPath,
      properties: ["openFile"],
      filters: [
        { name: "YAML", extensions: ["yml", "yaml"] },
        { name: "All files", extensions: ["*"] },
      ],
    });
    if (result.canceled || result.filePaths.length === 0) {
      return { ok: true, path: "" };
    }
    return { ok: true, path: result.filePaths[0] };
  });
  ipcMain.handle("easymanet:open-fleets-folder", async () => {
    const state = await runBridge(["state"]);
    if (!state.ok || !state.workspace || !state.workspace.fleets_dir) {
      return { ok: false, errors: state.errors || ["Fleets folder is unavailable"] };
    }
    const error = await shell.openPath(state.workspace.fleets_dir);
    if (error) {
      return { ok: false, errors: [error] };
    }
    return { ok: true };
  });
}

function runBridge(args, options = {}) {
  return new Promise((resolve) => {
    let bridge;
    try {
      bridge = bridgeCommand(args);
    } catch (error) {
      resolve({ ok: false, errors: [error.message] });
      return;
    }
    const child = spawn(bridge.command, bridge.args, {
      cwd: bridgeWorkingDirectory(),
      env: bridgeEnv(),
      stdio: ["ignore", "pipe", "pipe"],
    });
    let stdout = "";
    let stderr = "";
    let settled = false;

    const finish = (payload) => {
      if (settled) {
        return;
      }
      settled = true;
      clearTimeout(timer);
      resolve(payload);
    };

    const timeoutMs = options.timeoutMs || bridgeTimeoutMs;
    const timer = setTimeout(() => {
      child.kill();
      finish({ ok: false, errors: [`EasyMANET bridge timed out after ${timeoutMs / 1000}s`] });
    }, timeoutMs);

    child.stdout.on("data", (chunk) => {
      stdout += chunk.toString();
    });
    child.stderr.on("data", (chunk) => {
      stderr += chunk.toString();
    });
    child.on("error", (error) => {
      finish({ ok: false, errors: [error.message] });
    });
    child.on("close", () => {
      const text = stdout.trim();
      if (!text) {
        finish({ ok: false, errors: [stderr.trim() || "EasyMANET bridge returned no output"] });
        return;
      }
      try {
        finish(JSON.parse(text));
      } catch (error) {
        finish({ ok: false, errors: [error.message], raw: text, stderr: stderr.trim() });
      }
    });
  });
}

async function validatePayload(payload) {
  if (!payload || typeof payload !== "object" || Array.isArray(payload)) {
    return { ok: false, errors: ["Validation payload must be an object"] };
  }

  const config = typeof payload.config === "string" ? payload.config.trim() : "";
  if (!config) {
    return { ok: false, errors: ["Fleet config path is required"] };
  }
  if (hasTraversalSegment(config)) {
    return { ok: false, errors: ["Fleet config path must not contain traversal segments"] };
  }

  const node = typeof payload.node === "string" ? payload.node.trim() : "";
  if (node && !nodeNamePattern.test(node)) {
    return { ok: false, errors: ["Node name contains unsupported characters"] };
  }

  const resolved = await resolveConfigPath(config);
  if (!resolved.ok) {
    return resolved;
  }
  return { ok: true, config: resolved.config, node };
}

async function validateFlashPayload(payload) {
  const validated = await validatePayload(payload);
  if (!validated.ok) {
    return validated;
  }
  if (!validated.node) {
    return { ok: false, errors: ["Node name is required"] };
  }

  const device = typeof payload.device === "string" ? payload.device.trim() : "";
  if (!device) {
    return { ok: false, errors: ["Disk device is required"] };
  }

  const sshMode = typeof payload.sshMode === "string" ? payload.sshMode.trim() : "default";
  if (!sshModes.has(sshMode)) {
    return { ok: false, errors: ["Unsupported SSH mode"] };
  }

  return { ...validated, device, sshMode };
}

function flashArgs(payload) {
  const args = ["--config", payload.config, "--node", payload.node, "--device", payload.device];
  if (payload.sshMode === "enable") {
    args.push("--enable-ssh");
  } else if (payload.sshMode === "disable") {
    args.push("--disable-ssh");
  }
  return args;
}

async function resolveConfigPath(config) {
  const expanded = expandHome(config);
  if (path.isAbsolute(expanded)) {
    return existingFleetFile(expanded);
  }

  const state = await runBridge(["state"]);
  if (!state.ok || !state.workspace || !state.workspace.fleets_dir) {
    return { ok: false, errors: state.errors || ["Fleets folder is unavailable"] };
  }
  const fleetRoot = path.resolve(state.workspace.fleets_dir);
  const candidate = path.resolve(fleetRoot, expanded);
  if (!isInside(fleetRoot, candidate)) {
    return { ok: false, errors: ["Fleet config path must stay inside the Fleets folder"] };
  }
  return existingFleetFile(candidate);
}

function existingFleetFile(configPath) {
  for (const candidate of fleetPathCandidates(path.resolve(configPath))) {
    if (!fleetExtensions.has(path.extname(candidate).toLowerCase())) {
      continue;
    }
    try {
      const stat = fs.statSync(candidate);
      if (stat.isFile()) {
        return { ok: true, config: candidate };
      }
    } catch (_error) {
      // Try the next extension candidate.
    }
  }
  return { ok: false, errors: ["Fleet config file must exist and use .yml or .yaml"] };
}

function fleetPathCandidates(configPath) {
  if (path.extname(configPath)) {
    return [configPath];
  }
  return [configPath, `${configPath}.yml`, `${configPath}.yaml`];
}

function expandHome(value) {
  if (value === "~") {
    return app.getPath("home");
  }
  if (value.startsWith(`~${path.sep}`) || value.startsWith("~/") || value.startsWith("~\\")) {
    return path.join(app.getPath("home"), value.slice(2));
  }
  return value;
}

function hasTraversalSegment(value) {
  return value.split(/[\\/]+/).some((part) => part === "..");
}

function isInside(root, candidate) {
  const relative = path.relative(root, candidate);
  return Boolean(relative) && !relative.startsWith("..") && !path.isAbsolute(relative);
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
    path.join(repoRoot, "packages", "image", "src"),
    path.join(repoRoot, "apps", "cli", "src"),
    path.join(repoRoot, "apps", "desktop", "src"),
    path.join(repoRoot, "tools", "publish", "src"),
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
