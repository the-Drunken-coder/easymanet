const { app, BrowserWindow } = require("electron");
const { registerIpc } = require("./ipc");
const { createWindow, setDockIcon } = require("./window");

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
