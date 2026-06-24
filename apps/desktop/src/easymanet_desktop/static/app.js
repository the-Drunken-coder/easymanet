// Controller for the EasyMANET operator console.
// Markup builders live in render.js (EMRender); this file owns UI workflow wiring.
const {
  escapeHtml,
  formatBytes,
  imageItem,
  diskCard,
  validationMarkup,
  planMarkup,
  meshDiscoveryMarkup,
  meshTopologyView,
} = window.EMRender;

const state = window.EMState;
const { byId: $, detectMacPlatform } = window.EMDom;
const { nativeApi, postJson, errorDetail, errorMessage, getState, getImageUpdates, getDisks } = window.EMApi;
const { uniqueNodeNames, roleSshHint } = window.EMFleet;
const { diskInventorySignature } = window.EMDisk;
const {
  normalizeSshMode,
  sshModeLabel,
  flashAccessHint: flashAccessHintForAccess,
  imageReadinessSummary,
  imagesFullyCached,
  planImageSummary,
} = window.EMFlashUi;
const { emptyMeshMarkup } = window.EMMesh;

const workspacePath = $("workspace-path");
const fleetFolder = $("fleet-folder");
const fleetEmpty = $("fleet-empty");
const fleetEmptyPath = $("fleet-empty-path");
const fleetCount = $("fleet-count");
const fleetSelect = $("fleet-select");
const configInput = $("config-path");
const chooseConfig = $("choose-config");
const openFleetsFolder = $("open-fleets-folder");
const nodeSelect = $("node-name");
const nodeRoleChip = $("node-role");
const validationOutput = $("validation-output");
const imageCount = $("image-count");
const checkImageUpdatesButton = $("check-image-updates");
const images = $("images");
const diskPanel = $("disk-panel");
const disks = $("disks");
const showAllDisks = $("show-all-disks");
const allDisksWarning = $("all-disks-warning");
const flashPanel = $("flash-panel");
const flashReady = $("flash-ready");
const summaryNode = $("summary-node");
const selectedDisk = $("selected-disk");
const reviewStatus = $("review-status");
const reviewNode = $("review-node");
const reviewDisk = $("review-disk");
const reviewImage = $("review-image");
const reviewSsh = $("review-ssh");
const eraseWarning = $("erase-warning");
const sshAutoRadio = $("role-default-ssh");
const sshAutoHint = $("ssh-auto-hint");
const adminPasswordRow = $("admin-password-row");
const adminPasswordInput = $("admin-password");
const previewFlash = $("preview-flash");
const startFlash = $("start-flash");
const exportSupportBundle = $("export-support-bundle");
const flashStatus = $("flash-status");
const flashStatusText = $("flash-status-text");
const flashProgress = $("flash-progress");
const progressFill = $("progress-fill");
const progressText = $("progress-text");
const flashPlan = $("flash-plan");
const consoleWrap = $("console-wrap");
const flashOutput = $("flash-output");
const copyFlashLog = $("copy-flash-log");
const copySudo = $("copy-sudo");
const meshDiscoveryForm = $("mesh-discovery-form");
const meshStatusChip = $("mesh-status-chip");
const meshConfigSource = $("mesh-config-source");
const meshScanSubnet = $("mesh-scan-subnet");
const meshDiscover = $("mesh-discover");
const meshScanning = $("mesh-scanning");
const meshScanningDetail = $("mesh-scanning-detail");
const meshSummary = $("mesh-summary");
const meshCount = $("mesh-count");
const meshRadios = $("mesh-radios");
const meshOutput = $("mesh-output");
const copyMeshLog = $("copy-mesh-log");
const diagnosticsForm = $("diagnostics-form");
const diagnosticsStatusChip = $("diagnostics-status-chip");
const diagnosticsConfigSource = $("diagnostics-config-source");
const diagnosticsRun = $("diagnostics-run");
const diagnosticsExport = $("diagnostics-export");
const diagnosticsImportSource = $("diagnostics-import-source");
const diagnosticsImport = $("diagnostics-import");
const diagnosticsResult = $("diagnostics-result");
const diagnosticsOutput = $("diagnostics-output");
const diagnosticsCopy = $("diagnostics-copy");
const steps = {
  fleet: $("step-fleet"),
  node: $("step-node"),
  disk: $("step-disk"),
  flash: $("step-flash"),
};
const tabButtons = Array.from(document.querySelectorAll("[data-tab-target]"));
const tabPanels = Array.from(document.querySelectorAll("[data-tab-panel]"));

const isMac = detectMacPlatform();
const diskWatchIntervalMs = 2500;
let diskWatchTimer = null;

if (!nativeApi) {
  chooseConfig.hidden = true;
  openFleetsFolder.hidden = true;
  flashPanel.hidden = true;
} else if (nativeApi.onFlashEvent) {
  nativeApi.onFlashEvent(renderFlashEvent);
}
adminPasswordRow.hidden = true;
setupTabNavigation();

$("refresh").addEventListener("click", () => {
  refreshAll({ checkLatest: true }).catch(handleRefreshError);
});
checkImageUpdatesButton.addEventListener("click", () => {
  refreshImageUpdateStatus({ checkLatest: true, reportErrors: true }).catch(handleRefreshError);
});
fleetSelect.addEventListener("change", () => {
  selectFleetSource(fleetSelect.value);
});
meshConfigSource.addEventListener("change", () => {
  selectFleetSource(meshConfigSource.value);
});
configInput.addEventListener("input", () => {
  state.nodeLoadSeq += 1;
  resetNodeSelect("Update fleet path to load nodes");
  resetMeshDiscovery();
  updateMeshFleetSource();
  updateFlashControls();
});
configInput.addEventListener("change", () => {
  syncFleetSelect(configInput.value.trim());
  resetMeshDiscovery();
  updateMeshFleetSource();
  loadNodesForSelectedFleet().catch(handleNodeLoadError);
});
nodeSelect.addEventListener("change", () => {
  state.nodeName = nodeSelect.value.trim();
  updateRoleDefaultSsh();
  updateFlashControls();
});
chooseConfig.addEventListener("click", async () => {
  if (!nativeApi) {
    return;
  }
  const result = await nativeApi.chooseConfig();
  if (result.ok && result.path) {
    configInput.value = result.path;
    syncFleetSelect(result.path);
    updateMeshFleetSource();
    await loadNodesForSelectedFleet().catch(handleNodeLoadError);
    updateFlashControls();
  }
});
openFleetsFolder.addEventListener("click", async () => {
  if (!nativeApi) {
    return;
  }
  const result = await nativeApi.openFleetsFolder();
  if (!result.ok) {
    renderValidation({ ok: false, errors: result.errors || ["Could not open Fleets folder"] });
  }
});
showAllDisks.addEventListener("change", () => {
  updateDiskMode();
  loadDisks().catch(renderDiskError);
});
disks.addEventListener("click", (event) => {
  const button = event.target.closest("[data-device]");
  if (!button) {
    return;
  }
  state.diskDevice = button.dataset.device || "";
  loadDisks().catch(renderDiskError);
  updateFlashControls();
});
images.addEventListener("click", (event) => {
  const button = event.target.closest("[data-image-install-target]");
  if (!button) {
    return;
  }
  installImageUpdate(button.dataset.imageInstallTarget || "").catch((error) => {
    setFlashStatus("bad", errorMessage(error));
  });
});
document.querySelectorAll("input[name='ssh-mode']").forEach((input) => {
  input.addEventListener("change", updateFlashControls);
});
adminPasswordInput.addEventListener("input", updateFlashControls);

previewFlash.addEventListener("click", async () => {
  if (!nativeApi) {
    return;
  }
  setBusy(true);
  setFlashStatus("running", "Building flash plan (dry run)...");
  hideProgress();
  clearPlan();
  try {
    const response = await nativeApi.flashPlan(flashPayload());
    renderPlanResult(response);
  } catch (error) {
    setFlashStatus("bad", errorMessage(error));
  } finally {
    setBusy(false);
  }
});

startFlash.addEventListener("click", async () => {
  if (!nativeApi) {
    return;
  }
  resetConsole();
  clearPlan();
  state.lastFlashOk = false;
  setBusy(true);
  setFlashStatus("running", `Flashing ${state.diskDevice} for ${state.nodeName}...`);
  setProgress({ label: "Preparing", indeterminate: true });
  try {
    const response = await nativeApi.flash(flashPayload({ includeAdminPassword: true }));
    renderFlash(response);
    await refreshImageSidebar();
    await loadDisks().catch(renderDiskError);
  } catch (error) {
    hideProgress();
    setFlashStatus("bad", errorMessage(error));
  } finally {
    adminPasswordInput.value = "";
    setBusy(false);
  }
});

copySudo.addEventListener("click", async () => {
  if (!nativeApi || !state.sudoCommand) {
    return;
  }
  const result = await nativeApi.copyText(state.sudoCommand);
  if (result.ok) {
    showCopied(copySudo, "Copy Sudo Command");
  }
});
copyFlashLog.addEventListener("click", async () => {
  const logText = state.logLines.join("\n").trim();
  if (!nativeApi || !logText) {
    return;
  }
  const result = await nativeApi.copyText(logText);
  if (result.ok) {
    showCopied(copyFlashLog, "Copy Log");
  }
});
copyMeshLog.addEventListener("click", async () => {
  const logText = state.meshLogLines.join("\n").trim();
  if (!nativeApi || !logText) {
    return;
  }
  const result = await nativeApi.copyText(logText);
  if (result.ok) {
    showCopied(copyMeshLog, "Copy Log");
  }
});
exportSupportBundle.addEventListener("click", async () => {
  const payload = {
    config: state.configPath || configInput.value.trim(),
    node: state.nodeName || nodeSelect.value.trim(),
    include_disks: true,
    includeDisks: true,
  };
  try {
    const result = await postJson("/api/support/bundle", payload);
    if (result.ok) {
      appendLog("success", `Support bundle exported: ${result.path}`);
      setFlashStatus("ok", "Support bundle exported.");
    } else if (!result.canceled) {
      setFlashStatus("bad", (result.errors || [])[0] || "Support bundle export failed");
    }
  } catch (error) {
    setFlashStatus("bad", errorMessage(error));
  }
});
meshDiscoveryForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  await discoverMesh();
});
diagnosticsForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  await runDiagnostics();
});
diagnosticsExport.addEventListener("click", async () => {
  await exportDiagnosticsBundle();
});
diagnosticsImport.addEventListener("click", async () => {
  await importOfflineBootReport();
});
diagnosticsCopy.addEventListener("click", async () => {
  await copyDiagnosticsSummary();
});
$("validate-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  state.configPath = configInput.value.trim();
  state.nodeName = nodeSelect.value.trim();
  try {
    const response = await postJson("/api/validate", {
      config: state.configPath,
      node: state.nodeName,
    });
    renderNodeOptions(
      response.nodes || [],
      state.nodeName,
      response.node_roles || {},
      response.node_access || {}
    );
    renderValidation(response);
    updateFlashControls();
  } catch (error) {
    console.error("Validation request failed", error);
    renderValidation({ ok: false, errors: [errorMessage(error)] });
  }
});

async function refreshAll({ checkLatest = false } = {}) {
  try {
    await Promise.all([loadState({ checkLatest }), loadDisks()]);
  } catch (error) {
    handleRefreshError(error);
  }
}

async function loadState({ checkLatest = false } = {}) {
  try {
    const payload = await getState();
    if (!payload.ok) {
      throw new Error(errorDetail(payload) || "Could not load workspace state");
    }
    const workspace = payload.workspace || {};
    workspacePath.textContent = workspace.root || "";
    workspacePath.title = workspace.root || "";
    await renderFleets(workspace.fleet_files || [], workspace.fleets_dir || "");
    renderImageState(payload.images || {});
    if (checkLatest) {
      await refreshImageUpdateStatus({ checkLatest: true });
    }
    updateMeshFleetSource();
    updateFlashControls();
  } catch (error) {
    console.error("State refresh failed", error);
    renderStateError(error);
  }
}

function renderImageState(imagePayload) {
  const entries = Object.entries(imagePayload || {});
  state.images = imagePayload || {};
  imageCount.textContent = `${entries.length}`;
  images.innerHTML = entries
    .map(([target, image]) => imageItem(target, imageWithUpdate(target, image)))
    .join("");
}

function imageWithUpdate(target, image) {
  const update = state.imageUpdates[target] || {};
  return {
    ...(image || {}),
    ...update,
    installing: state.imageInstallTarget === target,
    anyInstallRunning: Boolean(state.imageInstallTarget),
  };
}

async function refreshImageUpdateStatus({ checkLatest = false, reportErrors = false } = {}) {
  const seq = state.imageUpdateSeq + 1;
  state.imageUpdateSeq = seq;
  if (checkLatest) {
    checkImageUpdatesButton.disabled = true;
    checkImageUpdatesButton.textContent = "Checking...";
  }
  try {
    const payload = await getImageUpdates({ checkLatest });
    if (seq !== state.imageUpdateSeq) {
      return;
    }
    if (!payload.ok) {
      throw new Error(errorDetail(payload) || "Could not check image releases");
    }
    state.imageUpdates = payload.updates || {};
    renderImageState(state.images);
  } catch (error) {
    console.debug("Image update check failed", error);
    if (reportErrors) {
      setFlashStatus("bad", errorMessage(error));
    }
  } finally {
    if (checkLatest) {
      checkImageUpdatesButton.disabled = false;
      checkImageUpdatesButton.textContent = "Check Updates";
    }
  }
}

async function refreshImageSidebar({ checkLatest = false } = {}) {
  if (state.imageLoadInFlight) {
    state.imageRefreshQueued = true;
    state.imageRefreshQueuedCheckLatest = state.imageRefreshQueuedCheckLatest || checkLatest;
    return;
  }
  state.imageLoadInFlight = true;
  try {
    const payload = await getState();
    if (!payload.ok) {
      throw new Error(errorDetail(payload) || "Could not refresh image state");
    }
    renderImageState(payload.images || {});
    if (checkLatest) {
      await refreshImageUpdateStatus({ checkLatest: true });
    }
    updateFlashControls();
  } catch (error) {
    console.debug("Image sidebar refresh failed", error);
  } finally {
    state.imageLoadInFlight = false;
    if (state.imageRefreshQueued) {
      const queuedCheckLatest = Boolean(state.imageRefreshQueuedCheckLatest);
      state.imageRefreshQueued = false;
      state.imageRefreshQueuedCheckLatest = false;
      refreshImageSidebar({ checkLatest: queuedCheckLatest });
    }
  }
}

async function installImageUpdate(target) {
  target = String(target || "").trim();
  if (!target || state.imageInstallTarget) {
    return;
  }
  state.imageInstallTarget = target;
  renderImageState(state.images);
  setFlashStatus("running", `Installing latest image for ${target}...`);
  try {
    const payload = await postJson("/api/image-updates/install", { target });
    if (!payload.ok) {
      throw new Error(errorDetail(payload) || "Image update install failed");
    }
    if (payload.image) {
      state.images[target] = payload.image;
    }
    if (payload.update) {
      state.imageUpdates[target] = payload.update;
    }
    await refreshImageSidebar({ checkLatest: true });
    const version = payload.version || (payload.image || {}).version || "latest";
    setFlashStatus("ok", payload.installed === false ? "Image cache is already current." : `Installed image ${version}.`);
  } finally {
    state.imageInstallTarget = "";
    renderImageState(state.images);
  }
}

async function loadDisks() {
  return refreshDisks({ renderIfUnchanged: true, reportErrors: true });
}

async function refreshDisks({ renderIfUnchanged, reportErrors }) {
  if (state.diskLoadInFlight) {
    return;
  }
  state.diskLoadInFlight = true;
  try {
    const payload = await getDisks(showAllDisks.checked);
    if (!payload.ok) {
      if (reportErrors) {
        disks.innerHTML = `<div class="inline-error">${escapeHtml((payload.errors || []).join("\n"))}</div>`;
      }
      state.diskDevice = "";
      updateFlashControls();
      return;
    }
    const signature = diskInventorySignature(payload.disks || []);
    if (renderIfUnchanged || signature !== state.diskSignature) {
      renderDisksPayload(payload, signature);
    }
  } catch (error) {
    if (reportErrors) {
      console.error("Disk refresh failed", error);
      renderDiskError(error);
    } else {
      console.debug("Disk watcher refresh failed", error);
    }
  } finally {
    state.diskLoadInFlight = false;
  }
}

function renderDisksPayload(payload, signature = diskInventorySignature(payload.disks || [])) {
  const diskRecords = payload.disks || [];
  state.diskSignature = signature;
  if (!diskRecords.length) {
    disks.innerHTML = `<div class="empty-state slim"><p class="empty-title">No disks found</p><p class="empty-meta">Insert an SD card, then refresh.</p></div>`;
    state.diskDevice = "";
    updateFlashControls();
    return;
  }
  if (state.diskDevice && !diskRecords.some((disk) => disk.device === state.diskDevice)) {
    state.diskDevice = "";
  }
  disks.innerHTML = diskRecords.map((disk) => diskCard(disk, state.diskDevice)).join("");
  updateFlashControls();
}

function renderValidation(payload) {
  validationOutput.hidden = false;
  validationOutput.className = `validation ${payload.ok ? "ok" : "bad"}`;
  validationOutput.innerHTML = validationMarkup(payload);
}

async function renderFleets(records, folder) {
  fleetFolder.textContent = folder || "";
  fleetFolder.title = folder || "";
  fleetEmptyPath.textContent = folder || "";
  fleetCount.textContent = `${records.length}`;
  resetFleetSelect(fleetSelect);
  resetFleetSelect(meshConfigSource);

  if (!records.length) {
    setFleetSelectEmpty(fleetSelect, "No fleet files found");
    setFleetSelectEmpty(meshConfigSource, "No fleet files found");
    fleetEmpty.hidden = false;
    configInput.value = "";
    updateMeshFleetSource();
    resetNodeSelect("No nodes available");
    updateFlashControls();
    return;
  }

  fleetEmpty.hidden = true;
  fleetSelect.disabled = false;
  meshConfigSource.disabled = false;
  for (const record of records) {
    addFleetOption(fleetSelect, record);
    addFleetOption(meshConfigSource, record);
  }

  const current = configInput.value.trim();
  const selected = current || records[0].path;
  configInput.value = selected;
  syncFleetSelect(selected);
  updateMeshFleetSource();
  await loadNodesForSelectedFleet(state.nodeName).catch(handleNodeLoadError);
  updateFlashControls();
}

function syncFleetSelect(path) {
  if (!path) {
    return;
  }
  syncFleetSelectElement(fleetSelect, path);
  syncFleetSelectElement(meshConfigSource, path);
}

function resetFleetSelect(select) {
  select.replaceChildren();
}

function setFleetSelectEmpty(select, label) {
  select.replaceChildren();
  select.disabled = true;
  select.add(new Option(label, ""));
}

function addFleetOption(select, record) {
  select.add(new Option(record.relative_path || record.name, record.path));
}

function syncFleetSelectElement(select, path) {
  if (select.disabled) {
    return;
  }
  const options = Array.from(select.options);
  if (options.some((option) => option.value === path)) {
    select.value = path;
    return;
  }
  const custom = new Option("Custom path", path);
  custom.dataset.custom = "true";
  select.add(custom, 0);
  select.value = path;
}

function selectFleetSource(path) {
  if (!path) {
    return;
  }
  configInput.value = path;
  syncFleetSelect(path);
  resetMeshDiscovery();
  updateMeshFleetSource();
  loadNodesForSelectedFleet().catch(handleNodeLoadError);
  updateFlashControls();
}

async function loadNodesForSelectedFleet(preferredNode = "") {
  const config = configInput.value.trim();
  const selectedNode = preferredNode || state.nodeName;
  const seq = state.nodeLoadSeq + 1;
  state.nodeLoadSeq = seq;
  state.configPath = config;

  if (!config) {
    resetNodeSelect("Select a fleet first");
    return;
  }

  resetNodeSelect("Loading nodes...");
  const response = await postJson("/api/validate", { config, node: "" });
  if (seq !== state.nodeLoadSeq) {
    return;
  }
  renderNodeOptions(
    response.nodes || [],
    selectedNode,
    response.node_roles || {},
    response.node_access || {}
  );
  if (!response.ok) {
    renderValidation(response);
  }
}

function renderNodeOptions(nodes, preferredNode = "", nodeRoles = {}, nodeAccess = {}) {
  const uniqueNodes = uniqueNodeNames(nodes);
  state.nodeRoles = { ...nodeRoles };
  state.nodeAccess = { ...nodeAccess };
  nodeSelect.replaceChildren();

  if (!uniqueNodes.length) {
    nodeSelect.add(new Option("No nodes found", ""));
    nodeSelect.disabled = true;
    state.nodeName = "";
    updateRoleDefaultSsh();
    updateFlashControls();
    return;
  }

  nodeSelect.add(new Option("Select a node", ""));
  for (const node of uniqueNodes) {
    nodeSelect.add(new Option(node, node));
  }

  if (preferredNode && uniqueNodes.includes(preferredNode)) {
    nodeSelect.value = preferredNode;
  } else if (uniqueNodes.length === 1) {
    nodeSelect.value = uniqueNodes[0];
  } else {
    nodeSelect.value = "";
  }

  nodeSelect.disabled = false;
  state.nodeName = nodeSelect.value.trim();
  updateRoleDefaultSsh();
  updateFlashControls();
}

function resetNodeSelect(label) {
  state.nodeName = "";
  state.nodeRoles = {};
  state.nodeAccess = {};
  nodeSelect.replaceChildren();
  nodeSelect.add(new Option(label, ""));
  nodeSelect.disabled = true;
  applyRoleDefaultSsh();
}

async function discoverMesh() {
  state.meshHasScanned = true;
  resetMeshLog();
  const config = configInput.value.trim();
  appendMeshLog("info", "Scan started.");
  appendMeshLog("info", `Fleet source: ${config || "none"}`);
  appendMeshLog("info", meshScanSubnet.checked ? "Local network scan enabled." : "Local network scan disabled.");
  setMeshBusy(true);
  meshSummary.hidden = true;
  meshRadios.setAttribute("aria-busy", "true");
  setMeshStatus("warn", "scanning");
  try {
    const response = await postJson("/api/mesh/discover", {
      config,
      scanSubnet: meshScanSubnet.checked,
    });
    appendMeshDiscoveryResult(response);
    renderMeshDiscovery(response);
  } catch (error) {
    const message = errorMessage(error);
    appendMeshLog("error", message);
    renderMeshDiscovery({ ok: false, errors: [message], nodes: [], links: [], candidates_checked: 0 });
  } finally {
    meshRadios.removeAttribute("aria-busy");
    setMeshBusy(false);
  }
}

function renderMeshDiscovery(payload) {
  const nodes = payload.nodes || payload.radios || [];
  const links = payload.links || [];
  state.meshNodes = nodes;
  state.meshLinks = links;
  meshCount.textContent = `${nodes.length}`;
  meshSummary.hidden = false;
  meshSummary.className = `validation ${payload.ok ? "ok" : "bad"}`;
  meshSummary.innerHTML = meshDiscoveryMarkup(payload);
  if (nodes.length) {
    meshRadios.className = "topology-view";
    meshRadios.innerHTML = meshTopologyView(payload);
    setMeshStatus(payload.ok ? "ok" : "warn", payload.ok ? `${nodes.length} nodes` : "partial results");
  } else {
    meshRadios.className = "mesh-grid";
    meshRadios.innerHTML = emptyMeshMarkup("No topology found", "No EasyMANET gateway API answered.");
    setMeshStatus(payload.ok ? "subtle" : "bad", payload.ok ? "none found" : "error");
  }
}

function resetMeshDiscovery() {
  state.meshHasScanned = false;
  state.meshNodes = [];
  state.meshLinks = [];
  meshCount.textContent = "0";
  meshSummary.hidden = true;
  meshSummary.innerHTML = "";
  meshRadios.className = "mesh-grid";
  meshRadios.innerHTML = emptyMeshMarkup("No topology found", "Run Scan Mesh to refresh this view.");
  setMeshStatus("subtle", "idle");
  resetMeshLog();
}

function setMeshBusy(busy) {
  state.meshBusy = busy;
  meshDiscover.disabled = busy;
  meshDiscover.textContent = busy ? "Scanning..." : "Scan Mesh";
  meshDiscover.setAttribute("aria-busy", busy ? "true" : "false");
  meshScanSubnet.disabled = busy;
  meshScanning.hidden = !busy;
  meshScanningDetail.textContent = meshScanSubnet.checked
    ? "Checking gateway APIs, fleet nodes, and local network candidates."
    : "Checking gateway APIs and fleet node candidates.";
  if (busy) {
    setMeshStatus("warn", "scanning");
  }
}

function setMeshStatus(tone, label) {
  meshStatusChip.textContent = label;
  meshStatusChip.className = `chip ${tone}`;
}

function resetMeshLog() {
  state.meshLogLines = [];
  meshOutput.replaceChildren();
  renderMeshLogPlaceholder();
  updateCopyMeshLogVisibility();
}

function renderMeshLogPlaceholder() {
  const line = document.createElement("div");
  line.className = "log-line info";
  const stamp = document.createElement("span");
  stamp.className = "log-time";
  stamp.textContent = "--:--:--";
  const body = document.createElement("span");
  body.className = "log-msg";
  body.textContent = "No mesh discovery activity yet.";
  line.append(stamp, body);
  meshOutput.appendChild(line);
}

function appendMeshLog(level, message) {
  const text = String(message || "").trim();
  if (!text) {
    return;
  }
  if (!state.meshLogLines.length) {
    meshOutput.replaceChildren();
  }
  const tone = level === "warning" ? "warn" : level === "error" ? "bad" : level === "success" ? "ok" : "info";
  const line = document.createElement("div");
  line.className = `log-line ${tone}`;
  const stamp = document.createElement("span");
  stamp.className = "log-time";
  stamp.textContent = new Date().toLocaleTimeString([], { hour12: false });
  const body = document.createElement("span");
  body.className = "log-msg";
  body.textContent = text;
  line.append(stamp, body);
  const stick = meshOutput.scrollHeight - meshOutput.scrollTop - meshOutput.clientHeight < 32;
  meshOutput.appendChild(line);
  if (stick) {
    meshOutput.scrollTop = meshOutput.scrollHeight;
  }
  const prefix = level === "warning" || level === "error" ? `${level}: ` : "";
  state.meshLogLines.push(`${stamp.textContent} ${prefix}${text}`);
  updateCopyMeshLogVisibility();
}

function appendMeshDiscoveryResult(payload) {
  const nodes = payload.nodes || payload.radios || [];
  const links = payload.links || [];
  const checked = Number(payload.candidates_checked) || 0;
  const summary = `${countLabel(nodes.length, "node")}, ${countLabel(links.length, "link")}, ${countLabel(checked, "candidate")} checked.`;
  if (payload.ok) {
    appendMeshLog(nodes.length ? "success" : "warning", `Scan complete: ${summary}`);
  } else {
    appendMeshLog("error", `Scan failed: ${summary}`);
  }
  for (const warning of payload.warnings || []) {
    appendMeshLog("warning", warning);
  }
  for (const error of payload.errors || []) {
    appendMeshLog("error", error);
  }
}

function countLabel(count, noun) {
  return `${count} ${noun}${count === 1 ? "" : "s"}`;
}

function updateCopyMeshLogVisibility() {
  copyMeshLog.disabled = !nativeApi || !state.meshLogLines.length;
  copyMeshLog.textContent = "Copy Log";
}

function updateMeshFleetSource() {
  const config = configInput.value.trim();
  meshConfigSource.title = config || "";
  diagnosticsConfigSource.textContent = config || "No fleet selected";
  diagnosticsConfigSource.title = config || "";
}

async function runDiagnostics() {
  setDiagnosticsBusy(true, "running");
  try {
    const response = await postJson("/api/diagnostics/run", {
      config: configInput.value.trim(),
    });
    renderDiagnostics(response);
  } catch (error) {
    renderDiagnosticsError(error);
  } finally {
    setDiagnosticsBusy(false);
  }
}

async function exportDiagnosticsBundle() {
  setDiagnosticsBusy(true, "exporting");
  try {
    const response = await postJson("/api/diagnostics/bundle", {
      config: configInput.value.trim(),
    });
    renderDiagnostics(response);
    if (response.bundle_path) {
      renderDiagnosticsResult({ ok: true, message: `Support bundle: ${response.bundle_path}` });
    }
  } catch (error) {
    renderDiagnosticsError(error);
  } finally {
    setDiagnosticsBusy(false);
  }
}

async function importOfflineBootReport() {
  const source = diagnosticsImportSource.value.trim();
  if (!source) {
    renderDiagnosticsResult({ ok: false, message: "Boot report source path is required." });
    return;
  }
  setDiagnosticsBusy(true, "importing");
  try {
    const response = await postJson("/api/diagnostics/import-boot-report", { source });
    const count = (response.imported || []).length;
    renderDiagnosticsResult({
      ok: Boolean(response.ok),
      message: response.ok ? `Imported ${count} boot report folder(s).` : errorDetail(response),
    });
  } catch (error) {
    renderDiagnosticsError(error);
  } finally {
    setDiagnosticsBusy(false);
  }
}

async function copyDiagnosticsSummary() {
  const text = diagnosticsOutput.textContent.trim();
  if (!nativeApi || !text) {
    return;
  }
  const result = await nativeApi.copyText(text);
  if (result.ok) {
    showCopied(diagnosticsCopy, "Copy Summary");
  } else {
    renderDiagnosticsResult({ ok: false, message: errorDetail(result) || "Could not copy support summary." });
  }
}

function renderDiagnostics(payload) {
  const summary = payload.summary || "";
  diagnosticsOutput.textContent = summary || JSON.stringify(payload, null, 2);
  setDiagnosticsStatus(payload.ok ? "ok" : "warn", payload.support_code || (payload.ok ? "ready" : "issues"));
  renderDiagnosticsResult({
    ok: Boolean(payload.ok),
    message: payload.bundle_path ? `Support bundle: ${payload.bundle_path}` : payload.support_code || "Diagnostics complete",
  });
}

function renderDiagnosticsError(error) {
  const message = errorMessage(error);
  setDiagnosticsStatus("bad", "error");
  renderDiagnosticsResult({ ok: false, message });
}

function renderDiagnosticsResult(payload) {
  diagnosticsResult.hidden = false;
  diagnosticsResult.className = `validation ${payload.ok ? "ok" : "bad"}`;
  diagnosticsResult.textContent = payload.message || "";
}

function setDiagnosticsBusy(busy, label = "running") {
  diagnosticsRun.disabled = busy;
  diagnosticsExport.disabled = busy;
  diagnosticsImport.disabled = busy;
  diagnosticsCopy.disabled = busy;
  setDiagnosticsStatus(busy ? "warn" : "subtle", busy ? label : "idle");
}

function setDiagnosticsStatus(tone, label) {
  diagnosticsStatusChip.textContent = label;
  diagnosticsStatusChip.className = `chip ${tone}`;
}

function flashPayload(options = {}) {
  state.configPath = configInput.value.trim();
  state.nodeName = nodeSelect.value.trim();
  const payload = {
    config: state.configPath,
    node: state.nodeName,
    device: state.diskDevice,
    sshMode: selectedSshMode(),
  };
  if (options.includeAdminPassword) {
    payload.adminPassword = adminPasswordInput.value;
  }
  return payload;
}

function selectedSshMode() {
  const checked = document.querySelector("input[name='ssh-mode']:checked");
  const value = checked ? checked.value : "auto";
  return normalizeSshMode(value);
}

function selectedSshLabel() {
  return sshModeLabel(selectedSshMode(), sshAutoHint.textContent || "role default");
}

function applyRoleDefaultSsh() {
  sshAutoRadio.checked = true;
  updateRoleDefaultSsh();
  updateFlashControls();
}

function selectedNodeRole() {
  const node = nodeSelect.value.trim();
  return node ? String(state.nodeRoles[node] || "").toLowerCase() : "";
}

function selectedNodeAccess(node = nodeSelect.value.trim()) {
  return node ? state.nodeAccess[node] || {} : {};
}

function flashAccessHint(node, payload = {}) {
  return flashAccessHintForAccess(selectedNodeAccess(node), payload);
}

function updateRoleDefaultSsh() {
  const role = selectedNodeRole();
  if (!role) {
    sshAutoHint.textContent = "role default";
    nodeRoleChip.hidden = true;
    return;
  }
  sshAutoHint.textContent = roleSshHint(role);
  nodeRoleChip.textContent = role;
  nodeRoleChip.hidden = false;
}

function setStep(stepEl, done) {
  if (!stepEl) {
    return;
  }
  if (!stepEl.dataset.label) {
    stepEl.dataset.label = stepEl.textContent;
  }
  stepEl.classList.toggle("done", done);
  stepEl.textContent = done ? "" : stepEl.dataset.label;
}

function updateFlashControls() {
  const config = configInput.value.trim();
  const node = nodeSelect.value.trim();
  const signature = currentFlashSignature(config, node);
  if (state.planSignature && state.planSignature !== signature) {
    state.planSignature = "";
    state.planImageSummary = "";
    clearPlan();
  }
  if (state.flashSignature && state.flashSignature !== signature) {
    state.flashSignature = "";
    state.lastFlashOk = false;
  }
  setStep(steps.fleet, Boolean(config));
  setStep(steps.node, Boolean(node));
  setStep(steps.disk, Boolean(state.diskDevice));
  setStep(steps.flash, state.lastFlashOk);
  if (!nativeApi) {
    return;
  }
  const ready = Boolean(config && node && state.diskDevice);
  const needsPassword = ready && isMac && !adminPasswordInput.value;
  adminPasswordRow.hidden = !isMac || !ready;
  previewFlash.disabled = !ready || state.flashBusy;
  startFlash.disabled = !ready || needsPassword || state.flashBusy;
  flashPanel.classList.toggle("ready", ready && !needsPassword && !state.flashBusy);
  flashPanel.classList.toggle("needs-attention", ready && needsPassword && !state.flashBusy);
  flashPanel.classList.toggle("busy", state.flashBusy);
  summaryNode.textContent = node || "—";
  selectedDisk.textContent = state.diskDevice || "None";

  let tone = "subtle";
  let label = "select a fleet";
  if (state.flashBusy) {
    tone = "warn";
    label = "in progress";
  } else if (!config) {
    label = "select a fleet";
  } else if (!node) {
    label = "select a node";
  } else if (!state.diskDevice) {
    label = "select a disk";
  } else if (needsPassword) {
    tone = "warn";
    label = "password required";
  } else {
    tone = "ok";
    label = "ready";
  }
  flashReady.textContent = label;
  flashReady.className = `chip ${tone}`;
  updateFlashReview({ node, ready, needsPassword, label, tone });
}

function currentFlashSignature(config = configInput.value.trim(), node = nodeSelect.value.trim()) {
  return [config, node, state.diskDevice, selectedSshMode()].join("|");
}

function updateFlashReview({ node, ready, needsPassword, label, tone }) {
  reviewNode.textContent = node || "Select a node";
  reviewDisk.textContent = state.diskDevice || "Select a disk";
  reviewSsh.textContent = selectedSshLabel();
  reviewImage.textContent = state.planImageSummary || imageReadinessSummary(state.images);
  eraseWarning.hidden = !state.diskDevice;
  reviewStatus.textContent = label;
  reviewStatus.className = `chip ${tone}`;
  reviewNode.classList.toggle("pending", !node);
  reviewDisk.classList.toggle("pending", !state.diskDevice);
  reviewImage.classList.toggle("pending", !state.planImageSummary && !imagesFullyCached(state.images));
  reviewSsh.classList.remove("pending");
  if (ready && !needsPassword && !state.flashBusy) {
    reviewStatus.textContent = state.planImageSummary ? "reviewed" : "ready";
    reviewStatus.className = `chip ${state.planImageSummary ? "ok" : tone}`;
  }
}

function updateDiskMode() {
  const showingAll = showAllDisks.checked;
  allDisksWarning.hidden = !showingAll;
  diskPanel.classList.toggle("danger-mode", showingAll);
}

function setupTabNavigation() {
  for (const button of tabButtons) {
    button.addEventListener("click", () => {
      if (button.disabled) {
        return;
      }
      activateTab(button.dataset.tabTarget);
    });
  }
  const selected = tabButtons.find((button) => button.getAttribute("aria-selected") === "true") || tabButtons[0];
  if (selected) {
    activateTab(selected.dataset.tabTarget);
  }
}

function activateTab(tabId) {
  if (!tabId) {
    return;
  }
  for (const button of tabButtons) {
    const selected = button.dataset.tabTarget === tabId;
    button.classList.toggle("active", selected);
    button.setAttribute("aria-selected", selected ? "true" : "false");
  }
  for (const panel of tabPanels) {
    const selected = panel.id === tabId;
    panel.hidden = !selected;
    panel.classList.toggle("active", selected);
  }
}

function startDiskWatcher() {
  if (diskWatchTimer) {
    return;
  }
  diskWatchTimer = setInterval(refreshDisksIfChanged, diskWatchIntervalMs);
  window.addEventListener("focus", refreshDisksIfChanged);
  document.addEventListener("visibilitychange", () => {
    if (!document.hidden) {
      refreshDisksIfChanged();
    }
  });
  window.addEventListener("beforeunload", stopDiskWatcher);
}

function stopDiskWatcher() {
  if (!diskWatchTimer) {
    return;
  }
  clearInterval(diskWatchTimer);
  diskWatchTimer = null;
}

function refreshDisksIfChanged() {
  if (state.flashBusy || document.hidden) {
    return;
  }
  refreshDisks({ renderIfUnchanged: false, reportErrors: false });
}

function setBusy(busy) {
  state.flashBusy = busy;
  document.body.classList.toggle("flash-busy", busy);
  updateFlashControls();
}

function setFlashStatus(tone, message) {
  flashStatus.hidden = false;
  flashStatus.className = `flash-status ${tone}`;
  flashStatusText.textContent = message;
}

function setProgress({ label = "", percent = null, detail = "", indeterminate = false } = {}) {
  flashProgress.hidden = false;
  if (indeterminate || percent === null) {
    flashProgress.classList.add("indeterminate");
    progressFill.style.width = "100%";
  } else {
    flashProgress.classList.remove("indeterminate");
    progressFill.style.width = `${Math.max(0, Math.min(100, percent))}%`;
  }
  progressText.textContent = detail ? `${label} · ${detail}` : label;
}

function hideProgress() {
  flashProgress.hidden = true;
  flashProgress.classList.remove("indeterminate");
  progressFill.style.width = "0";
}

function renderPlanCard(payload) {
  flashPlan.hidden = false;
  flashPlan.innerHTML = planMarkup(payload);
}

function clearPlan() {
  flashPlan.hidden = true;
  flashPlan.innerHTML = "";
}

function resetConsole() {
  state.logLines = [];
  state.sudoCommand = "";
  copySudo.hidden = true;
  copySudo.textContent = "Copy Sudo Command";
  flashOutput.replaceChildren();
  updateCopyFlashLogVisibility();
}

function appendLog(level, message) {
  const text = String(message || "").trim();
  if (!text) {
    return;
  }
  const tone = level === "warning" ? "warn" : level === "error" ? "bad" : level === "success" ? "ok" : "info";
  const line = document.createElement("div");
  line.className = `log-line ${tone}`;
  const stamp = document.createElement("span");
  stamp.className = "log-time";
  stamp.textContent = new Date().toLocaleTimeString([], { hour12: false });
  const body = document.createElement("span");
  body.className = "log-msg";
  body.textContent = text;
  line.append(stamp, body);
  const stick = flashOutput.scrollHeight - flashOutput.scrollTop - flashOutput.clientHeight < 32;
  flashOutput.appendChild(line);
  if (stick) {
    flashOutput.scrollTop = flashOutput.scrollHeight;
  }
  const prefix = level === "warning" || level === "error" ? `${level}: ` : "";
  state.logLines.push(`${stamp.textContent} ${prefix}${text}`);
  updateCopyFlashLogVisibility();
}

function updateCopyFlashLogVisibility() {
  consoleWrap.hidden = !state.logLines.length;
  copyFlashLog.textContent = "Copy Log";
}

function renderFlashEvent(event) {
  if (!event) {
    return;
  }
  const type = event.event_type || "";
  if (type === "download_progress") {
    const total = Number(event.total_bytes) || 0;
    const done = Number(event.downloaded_bytes) || 0;
    setProgress({
      label: "Downloading image",
      percent: typeof event.percent === "number" ? event.percent : total ? (done / total) * 100 : null,
      detail: total ? `${formatBytes(done)} / ${formatBytes(total)}` : formatBytes(done),
      indeterminate: !total && typeof event.percent !== "number",
    });
    return;
  }
  if (type === "download_completed") {
    refreshImageSidebar();
  }
  if (type === "dd_progress") {
    const written = Number(event.bytes);
    setProgress({
      label: "Writing image",
      indeterminate: true,
      detail: Number.isFinite(written) && written > 0 ? `${formatBytes(written)} written` : "",
    });
    return;
  }
  if (type === "plan") {
    renderPlanCard(event);
  }
  if (type === "inject_started") {
    setProgress({ label: "Writing boot payload", indeterminate: true });
  }
  if (type === "inject_result") {
    appendLog(event.ok === false ? "error" : "info", `${event.ok === false ? "failed" : "wrote"} ${event.message}`);
    return;
  }
  if (!event.message) {
    return;
  }
  appendLog(event.level || "info", event.message);
}

function renderPlanResult(payload) {
  state.sudoCommand = payload.sudo_command || "";
  copySudo.hidden = !state.sudoCommand;
  hideProgress();
  for (const warning of payload.warnings || []) {
    appendLog("warning", warning);
  }
  for (const error of payload.errors || []) {
    appendLog("error", error);
  }
  if (payload.ok) {
    state.planSignature = currentFlashSignature();
    state.planImageSummary = planImageSummary(payload);
    setFlashStatus("ok", "Dry run complete. No changes were made.");
    renderPlanCard(payload);
  } else {
    state.planSignature = "";
    state.planImageSummary = "";
    setFlashStatus("bad", (payload.errors || [])[0] || "Could not build the flash plan");
    if (payload.plan && Object.keys(payload.plan).length) {
      renderPlanCard(payload);
    }
  }
  updateFlashControls();
  updateCopyFlashLogVisibility();
}

function renderFlash(payload) {
  state.sudoCommand = payload.sudo_command || "";
  copySudo.hidden = !state.sudoCommand;
  hideProgress();
  for (const warning of payload.warnings || []) {
    appendLog("warning", warning);
  }
  for (const error of payload.errors || []) {
    appendLog("error", error);
  }
  if (payload.output) {
    for (const line of String(payload.output).split(/\r?\n/)) {
      appendLog("info", line);
    }
  }
  if (state.sudoCommand) {
    appendLog("warning", "Elevated privileges are required. Run the command below in Terminal, then refresh.");
    appendLog("info", state.sudoCommand);
  }
  if (payload.ok) {
    const node = payload.node || state.nodeName || "the node";
    const hint = flashAccessHint(node, payload);
    state.flashSignature = currentFlashSignature();
    state.lastFlashOk = true;
    appendLog("success", "Flash complete.");
    appendLog("info", hint);
    setFlashStatus("ok", `Flash complete. Insert the disk into ${node} and boot. ${hint}`);
  } else if (payload.canceled) {
    setFlashStatus("warn", "Flash canceled. The disk was not modified.");
  } else {
    setFlashStatus("bad", (payload.errors || [])[0] || "Flash failed");
  }
  updateFlashControls();
  updateCopyFlashLogVisibility();
}

function handleRefreshError(error) {
  console.error("Refresh failed", error);
  renderStateError(error);
  renderDiskError(error);
}

function renderStateError(error) {
  workspacePath.textContent = "Workspace unavailable";
  fleetFolder.textContent = "";
  fleetEmptyPath.textContent = "";
  fleetCount.textContent = "0";
  setFleetSelectEmpty(fleetSelect, "Workspace unavailable");
  setFleetSelectEmpty(meshConfigSource, "Workspace unavailable");
  resetNodeSelect("No nodes available");
  fleetEmpty.hidden = false;
  imageCount.textContent = "0";
  state.images = {};
  images.innerHTML = `<div class="inline-error">${escapeHtml(errorMessage(error))}</div>`;
  updateFlashControls();
}

function renderDiskError(error) {
  disks.innerHTML = `<div class="inline-error">${escapeHtml(errorMessage(error))}</div>`;
  state.diskDevice = "";
  selectedDisk.textContent = "None";
  updateFlashControls();
}

function showCopied(button, label) {
  button.textContent = "Copied";
  setTimeout(() => {
    button.textContent = label;
  }, 1200);
}

function handleNodeLoadError(error) {
  console.error("Node refresh failed", error);
  resetNodeSelect("Could not load nodes");
  renderValidation({ ok: false, errors: [errorMessage(error)] });
  updateFlashControls();
}

updateRoleDefaultSsh();
updateDiskMode();
updateMeshFleetSource();
resetMeshLog();
updateFlashControls();
refreshAll({ checkLatest: true }).catch(handleRefreshError).finally(startDiskWatcher);
