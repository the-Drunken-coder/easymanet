// Flash workflow presentation helpers for the EasyMANET desktop UI.
(function () {
  function normalizeSshMode(value) {
    return value === "auto" ? "default" : value;
  }

  function sshModeLabel(mode, autoHint) {
    if (mode === "enable") {
      return "On";
    }
    if (mode === "disable") {
      return "Off";
    }
    return `Auto (${autoHint || "role default"})`;
  }

  function flashAccessHint(access = {}, payload = {}) {
    const address = access.management_ip || "10.41.254.1";
    if ((payload.plan || {}).ssh_enabled === true) {
      return `Connect Ethernet, then SSH to root@${address}.`;
    }
    return "Connect Ethernet to the node management port.";
  }

  function imageReadinessSummary(images) {
    const entries = Object.entries(images || {});
    if (!entries.length) {
      return "No image targets found";
    }
    const missing = entries.filter(([, image]) => !imageCachePresent(image));
    if (!missing.length) {
      return entries.length === 1 ? "Image cache ready" : `${entries.length} image targets cached`;
    }
    const label = missing.length === 1 ? "target" : "targets";
    return `${missing.length} image ${label} will download during preview or flash`;
  }

  function imagesFullyCached(images) {
    const entries = Object.values(images || {});
    return Boolean(entries.length) && entries.every((image) => imageCachePresent(image));
  }

  function imageCachePresent(image) {
    return Boolean(image && image.cached_path && image.cache_present !== false);
  }

  function planImageSummary(payload) {
    const image = payload.image || {};
    const plan = payload.plan || {};
    const imagePath = image.cached_path || plan.base_image || image.url || "";
    const version = image.version ? ` ${image.version}` : "";
    if (imagePath) {
      return `Plan confirmed${version}: ${imagePath}`;
    }
    return "Plan confirmed exact image";
  }

  window.EMFlashUi = {
    normalizeSshMode,
    sshModeLabel,
    flashAccessHint,
    imageReadinessSummary,
    imagesFullyCached,
    planImageSummary,
  };
})();
