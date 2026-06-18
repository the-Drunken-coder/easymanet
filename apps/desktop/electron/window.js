const { app, BrowserWindow, nativeImage, shell } = require("electron");
const fs = require("node:fs");
const path = require("node:path");
const { appIconPngPath } = require("./constants");
const { indexHtmlPath } = require("./environment");

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

module.exports = { createWindow, setDockIcon, windowIconPath };
