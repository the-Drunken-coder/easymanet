const { app, BrowserWindow } = require("electron");
const { shutdownActiveBridgeProcesses } = require("./bridge-process");
const { registerIpc } = require("./ipc");
const { createWindow, setDockIcon } = require("./window");

let bridgeShutdownPromise = null;
let quitAfterBridgeShutdown = false;

app.on("before-quit", (event) => {
  if (quitAfterBridgeShutdown) {
    return;
  }
  event.preventDefault();
  if (bridgeShutdownPromise) {
    return;
  }
  bridgeShutdownPromise = shutdownActiveBridgeProcesses()
    .then(() => {
      quitAfterBridgeShutdown = true;
      app.quit();
    })
    .catch((error) => {
      bridgeShutdownPromise = null;
      console.error(`Could not stop active EasyMANET bridge processes: ${error.message}`);
    });
});

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
