const { contextBridge, ipcRenderer } = require("electron");

contextBridge.exposeInMainWorld("easymanet", {
  getState: () => ipcRenderer.invoke("easymanet:state"),
  getImageUpdates: () => ipcRenderer.invoke("easymanet:image-updates"),
  installImageUpdate: (target) => ipcRenderer.invoke("easymanet:image-update-install", { target }),
  getDisks: (includeAll = false) => ipcRenderer.invoke("easymanet:disks", { includeAll }),
  validate: (payload) => ipcRenderer.invoke("easymanet:validate", payload),
  discoverMesh: (payload) => ipcRenderer.invoke("easymanet:mesh-discover", payload),
  exportSupportBundle: (payload) => ipcRenderer.invoke("easymanet:support-bundle", payload),
  runDiagnostics: (payload) => ipcRenderer.invoke("easymanet:diagnostics-run", payload),
  exportDiagnosticsBundle: (payload) => ipcRenderer.invoke("easymanet:diagnostics-bundle", payload),
  importBootReport: (payload) => ipcRenderer.invoke("easymanet:diagnostics-import-boot-report", payload),
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
