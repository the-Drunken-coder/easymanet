const { contextBridge, ipcRenderer } = require("electron");

contextBridge.exposeInMainWorld("easymanet", {
  getState: () => ipcRenderer.invoke("easymanet:state"),
  getDisks: (includeAll = false) => ipcRenderer.invoke("easymanet:disks", { includeAll }),
  validate: (payload) => ipcRenderer.invoke("easymanet:validate", payload),
  chooseConfig: () => ipcRenderer.invoke("easymanet:choose-config"),
  openFleetsFolder: () => ipcRenderer.invoke("easymanet:open-fleets-folder"),
});
