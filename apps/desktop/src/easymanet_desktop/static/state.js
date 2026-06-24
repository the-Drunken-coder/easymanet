// Shared controller state and DOM helpers for the EasyMANET desktop UI.
(function () {
  const state = {
    configPath: "",
    nodeName: "",
    diskDevice: "",
    sudoCommand: "",
    nodeLoadSeq: 0,
    nodeRoles: {},
    nodeAccess: {},
    images: {},
    imageUpdates: {},
    imageUpdateSeq: 0,
    imageInstallTarget: "",
    imageLoadInFlight: false,
    imageRefreshQueued: false,
    diskSignature: "",
    diskLoadInFlight: false,
    flashBusy: false,
    lastFlashOk: false,
    meshBusy: false,
    meshHasScanned: false,
    meshNodes: [],
    meshLinks: [],
    meshLogLines: [],
    flashSignature: "",
    planSignature: "",
    planImageSummary: "",
    logLines: [],
  };

  const byId = (id) => document.getElementById(id);

  function detectMacPlatform() {
    const nav = window.navigator || {};
    const platform = String(nav.userAgentData?.platform || nav.platform || nav.userAgent || "").toLowerCase();
    return platform.includes("mac");
  }

  window.EMState = state;
  window.EMDom = {
    byId,
    detectMacPlatform,
  };
})();
