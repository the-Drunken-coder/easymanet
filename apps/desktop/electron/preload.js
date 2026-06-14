const { contextBridge, ipcRenderer } = require("electron");

contextBridge.exposeInMainWorld("easymanet", {
  getState: () => ipcRenderer.invoke("easymanet:state"),
  getDisks: (includeAll = false) => ipcRenderer.invoke("easymanet:disks", { includeAll }),
  validate: (payload) => ipcRenderer.invoke("easymanet:validate", payload),
  discoverMesh: (payload) => ipcRenderer.invoke("easymanet:mesh-discover", payload),
  flashPlan: (payload) => ipcRenderer.invoke("easymanet:flash-plan", payload),
  flash: (payload) => ipcRenderer.invoke("easymanet:flash", payload),
  onFlashEvent: (callback) => {
    const listener = (_event, payload) => callback(payload);
    ipcRenderer.on("easymanet:flash-event", listener);
    return () => ipcRenderer.removeListener("easymanet:flash-event", listener);
  },
  copyText: (text) => ipcRenderer.invoke("easymanet:copy-text", { text }),
  chooseConfig: () => ipcRenderer.invoke("easymanet:choose-config"),
  openFleetsFolder: () => ipcRenderer.invoke("easymanet:open-fleets-folder"),
});
