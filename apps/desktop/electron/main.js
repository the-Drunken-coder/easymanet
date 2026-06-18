const { app, BrowserWindow, clipboard, dialog, ipcMain, nativeImage, shell } = require("electron");
const { spawn } = require("node:child_process");
const path = require("node:path");
const fs = require("node:fs");
const { hasTraversalSegment, resolveConfigPath } = require("./path-utils");

const repoRoot = path.resolve(__dirname, "../../..");
const appIconPngPath = path.join(__dirname, "assets", "easymanet-icon.png");
const nodeNamePattern = /^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$/;
const bridgeTimeoutMs = 15000;
const meshBridgeTimeoutMs = 45000;
const flashBridgeTimeoutMs = 30 * 60 * 1000;
const sshModes = new Set(["default", "enable", "disable"]);

function booleanFlag(value) {
  if (typeof value === "string") {
    const normalized = value.trim().toLowerCase();
    return normalized === "true" || normalized === "1" || normalized === "yes" || normalized === "on";
  }
  return value === true || value === 1;
}

function createWindow() {
  const win = new BrowserWindow({
    width: 1180,
    height: 780,
    minWidth: 760,
    minHeight: 560,
    title: "EasyMANET",
    icon: windowIconPath(),
    backgroundColor: "#0b1014",
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
  setDockIcon();
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

function windowIconPath() {
  return fs.existsSync(appIconPngPath) ? appIconPngPath : undefined;
}

function setDockIcon() {
  if (process.platform !== "darwin" || !app.dock || !fs.existsSync(appIconPngPath)) {
    return;
  }
  const icon = nativeImage.createFromPath(appIconPngPath);
  if (!icon.isEmpty()) {
    app.dock.setIcon(icon);
  }
}

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
  ipcMain.handle("easymanet:mesh-discover", async (_event, payload = {}) => {
    const validated = await validateMeshPayload(payload);
    if (!validated.ok) {
      return validated;
    }
    const args = ["mesh-discover"];
    if (validated.config) {
      args.push("--config", validated.config);
    }
    if (validated.scanSubnet) {
      args.push("--scan-subnet");
    }
    return runBridge(args, { timeoutMs: meshBridgeTimeoutMs });
  });
  ipcMain.handle("easymanet:flash", async (event, payload = {}) => {
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
    if (process.platform === "darwin") {
      if (!validated.adminPassword) {
        return { ok: false, errors: ["Mac administrator password is required for flashing"] };
      }
      return runFlashWithAdministratorPrivileges(validated, {
        timeoutMs: flashBridgeTimeoutMs,
        webContents: event.sender,
        adminPassword: validated.adminPassword,
      });
    }
    return runBridgeStreaming(["flash", ...flashArgs(validated), "--yes"], {
      timeoutMs: flashBridgeTimeoutMs,
      webContents: event.sender,
    });
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
  return runBridgeJson(args, { timeoutMs: options.timeoutMs || bridgeTimeoutMs });
}

function runBridgeJson(args, options = {}) {
  return runBridgeProcess(args, {
    timeoutMs: options.timeoutMs || bridgeTimeoutMs,
    onStdout: (state, chunk) => {
      state.stdout += chunk;
    },
    onClose: (state, finish) => {
      finish(parseBridgeJsonOutput(state.stdout, state.stderr));
    },
  });
}

function runBridgeStreaming(args, options = {}) {
  return runBridgeProcess(args, {
    timeoutMs: options.timeoutMs || flashBridgeTimeoutMs,
    onStdout: (state, chunk) => {
      state.stdout += chunk;
      state.stdout = processBridgeStreamBuffer(state.stdout, options.webContents, (payload) => {
        state.finalPayload = payload;
      });
    },
    onClose: (state, finish) => {
      const remaining = state.stdout.trim();
      if (remaining) {
        processBridgeStreamLine(remaining, options.webContents, (payload) => {
          state.finalPayload = payload;
        });
      }
      if (state.finalPayload) {
        finish(state.finalPayload);
        return;
      }
      finish({
        ok: false,
        errors: [state.stderr.trim() || "EasyMANET bridge returned no flash result"],
        raw: state.fullStdout.trim(),
      });
    },
  });
}

async function runFlashWithAdministratorPrivileges(validated, options = {}) {
  const prepared = await runBridgeStreaming(["prepare-flash", ...flashArgs(validated)], {
    timeoutMs: options.timeoutMs || flashBridgeTimeoutMs,
    webContents: options.webContents,
  });
  if (!prepared.ok) {
    return prepared;
  }
  sendBridgeFlashEvent(options.webContents, {
    type: "event",
    event_type: "auth_required",
    level: "info",
    message: "Administrator authentication is required to write the selected disk.",
  });
  let stage = null;
  try {
    stage = stageElevatedFlashInputs(validated, prepared);
    const stagedPayload = {...validated, config: stage.configPath};
    const stagedImage = stage.imagePath ? {...prepared.image, cached_path: stage.imagePath} : prepared.image || {};
    const args = ["flash", ...flashArgs(stagedPayload), "--yes", ...baseImageArgs(stagedImage)];
    return await runBridgeWithAdministratorPrivileges(args, {...options, stage});
  } catch (error) {
    cleanupElevatedStage(stage);
    return {ok: false, errors: [error.message]};
  }
}

function runBridgeWithAdministratorPrivileges(args, options = {}) {
  return new Promise((resolve) => {
    let bridge;
    try {
      bridge = elevatedBridgeCommand(args, options.stage);
    } catch (error) {
      cleanupElevatedStage(options.stage);
      resolve({ ok: false, errors: [error.message] });
      return;
    }

    const timeoutMs = options.timeoutMs || flashBridgeTimeoutMs;
    const effectiveTimeoutMs = timeoutMs + 60000;
    const sudo = sudoBridgeCommand(bridge);
    const child = spawn(sudo.command, sudo.args, {
      cwd: bridge.cwd || elevatedTempRoot(),
      env: elevatedBridgeEnv(bridge.env || {}),
      stdio: ["pipe", "pipe", "pipe"],
      detached: process.platform !== "win32",
    });
    const state = {
      stdout: "",
      fullStdout: "",
      stderr: "",
      finalPayload: null,
    };
    let settled = false;

    const finish = (payload) => {
      if (settled) {
        return;
      }
      settled = true;
      clearTimeout(timer);
      cleanupElevatedStage(options.stage);
      resolve(payload);
    };

    const timer = setTimeout(() => {
      terminateElevatedBridge(child);
      finish({ ok: false, errors: [`Administrator flash timed out after ${effectiveTimeoutMs / 1000}s`] });
    }, effectiveTimeoutMs);

    child.stdout.on("data", (chunk) => {
      const text = chunk.toString();
      state.fullStdout += text;
      state.stdout += text;
      state.stdout = processBridgeStreamBuffer(state.stdout, options.webContents, (payload) => {
        state.finalPayload = payload;
      });
    });
    child.stderr.on("data", (chunk) => {
      state.stderr += chunk.toString();
    });
    child.on("error", (error) => {
      finish({ ok: false, errors: [error.message] });
    });
    child.on("close", () => {
      const remaining = state.stdout.trim();
      if (remaining) {
        processBridgeStreamLine(remaining, options.webContents, (payload) => {
          state.finalPayload = payload;
        });
      }
      if (state.finalPayload) {
        finish(state.finalPayload);
        return;
      }
      finish(parseElevatedBridgeOutput(state.fullStdout, state.stderr, options.webContents));
    });
    child.stdin.write(`${options.adminPassword || ""}\n`);
    child.stdin.end();
  });
}

function terminateElevatedBridge(child) {
  if (process.platform !== "win32" && child.pid) {
    try {
      process.kill(-child.pid, "SIGTERM");
      const killTimer = setTimeout(() => {
        try {
          process.kill(-child.pid, "SIGKILL");
        } catch (_error) {
          // Process already exited.
        }
      }, 5000);
      if (typeof killTimer.unref === "function") {
        killTimer.unref();
      }
      return;
    } catch (_error) {
      // Fall through to killing the wrapper process.
    }
  }
  child.kill("SIGTERM");
}

function runBridgeProcess(args, handlers) {
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
    const state = {
      stdout: "",
      fullStdout: "",
      stderr: "",
      finalPayload: null,
    };
    let settled = false;

    const finish = (payload) => {
      if (settled) {
        return;
      }
      settled = true;
      clearTimeout(timer);
      resolve(payload);
    };

    const timeoutMs = handlers.timeoutMs;
    const timer = setTimeout(() => {
      child.kill();
      finish({ ok: false, errors: [`EasyMANET bridge timed out after ${timeoutMs / 1000}s`] });
    }, timeoutMs);

    child.stdout.on("data", (chunk) => {
      const text = chunk.toString();
      state.fullStdout += text;
      handlers.onStdout(state, text);
    });
    child.stderr.on("data", (chunk) => {
      state.stderr += chunk.toString();
    });
    child.on("error", (error) => {
      finish({ ok: false, errors: [error.message] });
    });
    child.on("close", () => {
      handlers.onClose(state, finish);
    });
  });
}

function parseElevatedBridgeOutput(stdout, stderr, webContents) {
  const text = stdout.trim();
  const errorText = stderr.trim();
  if (!text) {
    if (errorText.includes("Sorry, try again") || errorText.includes("incorrect password")) {
      return { ok: false, errors: ["Administrator authentication failed"] };
    }
    if (errorText.includes("a password is required")) {
      return { ok: false, errors: ["Mac administrator password is required for flashing"] };
    }
    return { ok: false, errors: [errorText || "Administrator flash returned no output"] };
  }

  let finalPayload = null;
  const outputLines = [];
  for (const line of text.split(/\r?\n/)) {
    const trimmed = line.trim();
    if (!trimmed) {
      continue;
    }
    try {
      const payload = JSON.parse(trimmed);
      if (payload.type === "result") {
        finalPayload = payload;
      } else if (payload.type === "event") {
        sendBridgeFlashEvent(webContents, payload);
        outputLines.push(bridgeEventOutputLine(payload));
      } else if (Object.prototype.hasOwnProperty.call(payload, "ok")) {
        finalPayload = payload;
      }
    } catch (_error) {
      sendBridgeFlashEvent(webContents, {
        type: "event",
        event_type: "bridge_output",
        level: "info",
        message: trimmed,
      });
      outputLines.push(trimmed);
    }
  }
  if (finalPayload) {
    if (outputLines.length && !finalPayload.output) {
      finalPayload.output = outputLines.join("\n");
    }
    return finalPayload;
  }
  return parseBridgeJsonOutput(text, errorText);
}

function parseBridgeJsonOutput(stdout, stderr) {
  const text = stdout.trim();
  if (!text) {
    return { ok: false, errors: [stderr.trim() || "EasyMANET bridge returned no output"] };
  }
  try {
    return JSON.parse(text);
  } catch (error) {
    return { ok: false, errors: [error.message], raw: text, stderr: stderr.trim() };
  }
}

function stageElevatedFlashInputs(validated, plan) {
  const root = fs.mkdtempSync(path.join(elevatedTempRoot(), "easymanet-flash-"));
  const inputDir = path.join(root, "input");
  const sourceDir = path.join(root, "src");
  const workspaceDir = path.join(root, "workspace");
  fs.mkdirSync(inputDir, {recursive: true});
  fs.mkdirSync(sourceDir, {recursive: true});
  fs.mkdirSync(workspaceDir, {recursive: true});

  const configPath = path.join(inputDir, path.basename(validated.config) || "fleet.yml");
  fs.copyFileSync(validated.config, configPath);
  fs.chmodSync(configPath, 0o600);

  const sourceImagePath = String((plan.image || {}).cached_path || (plan.image || {}).path || "");
  let imagePath = "";
  if (sourceImagePath && !sourceImagePath.startsWith("<")) {
    imagePath = path.join(inputDir, path.basename(sourceImagePath));
    fs.copyFileSync(sourceImagePath, imagePath);
    fs.chmodSync(imagePath, 0o644);
  }

  copyPythonPackage(path.join(repoRoot, "packages", "core", "src", "easymanet"), path.join(sourceDir, "easymanet"));
  copyPythonPackage(path.join(repoRoot, "apps", "cli", "src", "easymanet_cli"), path.join(sourceDir, "easymanet_cli"));
  copyPythonPackage(
    path.join(repoRoot, "apps", "desktop", "src", "easymanet_desktop"),
    path.join(sourceDir, "easymanet_desktop")
  );

  return {
    root,
    configPath,
    imagePath,
    sourceRoots: [sourceDir],
    workspaceDir,
  };
}

function copyPythonPackage(from, to) {
  if (!fs.existsSync(from)) {
    return;
  }
  fs.cpSync(from, to, {
    recursive: true,
    filter: (src) => !src.includes(`${path.sep}__pycache__${path.sep}`),
  });
}

function cleanupElevatedStage(stage) {
  if (!stage || !stage.root) {
    return;
  }
  const root = path.resolve(stage.root);
  if (!root.startsWith(path.resolve(elevatedTempRoot()) + path.sep)) {
    return;
  }
  try {
    fs.rmSync(root, {recursive: true, force: true});
  } catch (_error) {
    // Root-owned files should not block the desktop result.
  }
}

function baseImageArgs(image) {
  const imagePath = String(image.cached_path || image.path || "");
  if (!imagePath || imagePath.startsWith("<")) {
    return [];
  }
  const args = ["--base-image", imagePath];
  const sha256 = String(image.sha256 || "");
  if (sha256) {
    args.push("--image-sha256", sha256);
  }
  return args;
}

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

function bridgeEventOutputLine(payload) {
  const message = String(payload.message || payload.event_type || "").trim();
  const prefix = payload.level === "warning" ? "warning: " : payload.level === "error" ? "error: " : "";
  return `${prefix}${message}`.trim();
}

function processBridgeStreamBuffer(buffer, webContents, setFinalPayload) {
  const lines = buffer.split(/\r?\n/);
  const tail = lines.pop() || "";
  for (const line of lines) {
    const text = line.trim();
    if (!text) {
      continue;
    }
    processBridgeStreamLine(text, webContents, setFinalPayload);
  }
  return tail;
}

function processBridgeStreamLine(text, webContents, setFinalPayload) {
  try {
    const payload = JSON.parse(text);
    if (payload.type === "event") {
      sendBridgeFlashEvent(webContents, payload);
    } else if (payload.type === "result" || Object.prototype.hasOwnProperty.call(payload, "ok")) {
      setFinalPayload(payload);
    }
  } catch (_error) {
    sendBridgeFlashEvent(webContents, {
      type: "event",
      event_type: "bridge_output",
      level: "info",
      message: text,
    });
  }
}

function sendBridgeFlashEvent(webContents, payload) {
  if (!webContents || (typeof webContents.isDestroyed === "function" && webContents.isDestroyed())) {
    return;
  }
  try {
    webContents.send("easymanet:flash-event", payload);
  } catch (_error) {
    // The renderer may close between the isDestroyed check and the send call.
  }
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

  const resolved = await resolveConfigPath(config, {
    runBridge,
    homeDir: () => app.getPath("home"),
  });
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

  const adminPassword = typeof payload.adminPassword === "string" ? payload.adminPassword : "";

  return { ...validated, device, sshMode, adminPassword };
}

async function validateMeshPayload(payload) {
  if (!payload || typeof payload !== "object" || Array.isArray(payload)) {
    return { ok: false, errors: ["Mesh discovery payload must be an object"] };
  }

  const rawConfig = typeof payload.config === "string" ? payload.config.trim() : "";
  let config = "";
  if (rawConfig) {
    if (hasTraversalSegment(rawConfig)) {
      return { ok: false, errors: ["Fleet config path must not contain traversal segments"] };
    }
    const resolved = await resolveConfigPath(rawConfig, {
      runBridge,
      homeDir: () => app.getPath("home"),
    });
    if (!resolved.ok) {
      return resolved;
    }
    config = resolved.config;
  }

  return {
    ok: true,
    config,
    scanSubnet: booleanFlag(payload.scanSubnet) || booleanFlag(payload.scan_subnet),
  };
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
