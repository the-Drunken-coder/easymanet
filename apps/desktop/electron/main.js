const { app, BrowserWindow, dialog, ipcMain, shell } = require("electron");
const { spawn } = require("node:child_process");
const path = require("node:path");
const fs = require("node:fs");

const repoRoot = path.resolve(__dirname, "../../..");
const staticRoot = path.join(repoRoot, "apps", "desktop", "src", "easymanet_desktop", "static");
const indexHtml = path.join(staticRoot, "index.html");

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
            openFleetsFolderVisible: !document.querySelector("#open-fleets-folder")?.hidden
          });
        })()
      `);
      console.log(state);
      app.quit();
    });
  }
  win.loadFile(indexHtml);
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
  ipcMain.handle("easymanet:validate", (_event, payload = {}) => {
    const args = ["validate", "--config", String(payload.config || "")];
    if (payload.node) {
      args.push("--node", String(payload.node));
    }
    return runBridge(args);
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

function runBridge(args) {
  return new Promise((resolve) => {
    const child = spawn(pythonPath(), ["-m", "easymanet_desktop.bridge", ...args], {
      cwd: repoRoot,
      env: bridgeEnv(),
      stdio: ["ignore", "pipe", "pipe"],
    });
    let stdout = "";
    let stderr = "";

    child.stdout.on("data", (chunk) => {
      stdout += chunk.toString();
    });
    child.stderr.on("data", (chunk) => {
      stderr += chunk.toString();
    });
    child.on("error", (error) => {
      resolve({ ok: false, errors: [error.message] });
    });
    child.on("close", () => {
      const text = stdout.trim();
      if (!text) {
        resolve({ ok: false, errors: [stderr.trim() || "EasyMANET bridge returned no output"] });
        return;
      }
      try {
        resolve(JSON.parse(text));
      } catch (error) {
        resolve({ ok: false, errors: [error.message], raw: text, stderr: stderr.trim() });
      }
    });
  });
}

function pythonPath() {
  if (process.env.EASYMANET_PYTHON) {
    return process.env.EASYMANET_PYTHON;
  }
  if (process.env.VIRTUAL_ENV) {
    return path.join(process.env.VIRTUAL_ENV, "bin", "python");
  }
  const localVenv = path.join(repoRoot, ".codex-venv", "bin", "python");
  if (fs.existsSync(localVenv)) {
    return localVenv;
  }
  return "python3";
}

function bridgeEnv() {
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
