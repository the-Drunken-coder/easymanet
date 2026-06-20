const { clipboard, dialog, ipcMain, shell } = require("electron");
const { flashBridgeTimeoutMs, meshBridgeTimeoutMs } = require("./constants");
const { runBridge, runBridgeStreaming } = require("./bridge-process");
const { runFlashWithAdministratorPrivileges } = require("./elevated-flash");
const { flashArgs, validateFlashPayload, validateMeshPayload, validatePayload } = require("./validation");

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
  ipcMain.handle("easymanet:support-bundle", async (_event, payload = {}) => {
    const state = await runBridge(["state"]);
    const defaultPath = state.ok && state.workspace ? state.workspace.diagnostics_dir : undefined;
    const result = await dialog.showSaveDialog({
      title: "Export EasyMANET support bundle",
      defaultPath,
      filters: [{ name: "Zip archive", extensions: ["zip"] }],
    });
    if (result.canceled || !result.filePath) {
      return { ok: false, canceled: true, errors: ["Support bundle export canceled"] };
    }
    const args = ["support-bundle", "--output", result.filePath];
    if (payload.config) {
      args.push("--config", String(payload.config));
    }
    if (payload.node) {
      args.push("--node", String(payload.node));
    }
    if (payload.bootReport) {
      args.push("--boot-report", String(payload.bootReport));
    }
    if (payload.includeDisks) {
      args.push("--include-disks");
    }
    return runBridge(args);
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

module.exports = { registerIpc };
