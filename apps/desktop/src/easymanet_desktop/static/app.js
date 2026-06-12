// Controller for the EasyMANET operator console.
// Markup builders live in render.js (EMRender); this file owns state and wiring.
const { escapeHtml, formatBytes, imageItem, diskCard, validationMarkup, planMarkup } = window.EMRender;

const state = {
  configPath: "",
  nodeName: "",
  diskDevice: "",
  sudoCommand: "",
  nodeLoadSeq: 0,
  nodeRoles: {},
  flashBusy: false,
  lastFlashOk: false,
  logLines: [],
};

const $ = (id) => document.getElementById(id);
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
const images = $("images");
const disks = $("disks");
const showAllDisks = $("show-all-disks");
const flashPanel = $("flash-panel");
const flashReady = $("flash-ready");
const summaryNode = $("summary-node");
const selectedDisk = $("selected-disk");
const sshAutoRadio = $("role-default-ssh");
const sshAutoHint = $("ssh-auto-hint");
const adminPasswordRow = $("admin-password-row");
const adminPasswordInput = $("admin-password");
const previewFlash = $("preview-flash");
const startFlash = $("start-flash");
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
const steps = {
  fleet: $("step-fleet"),
  node: $("step-node"),
  disk: $("step-disk"),
  flash: $("step-flash"),
};

const nativeApi = window.easymanet || null;
const isMac = navigator.platform.toLowerCase().includes("mac");

if (!nativeApi) {
  chooseConfig.hidden = true;
  openFleetsFolder.hidden = true;
  flashPanel.hidden = true;
} else if (nativeApi.onFlashEvent) {
  nativeApi.onFlashEvent(renderFlashEvent);
}
adminPasswordRow.hidden = !nativeApi || !isMac;

$("refresh").addEventListener("click", () => {
  refreshAll().catch(handleRefreshError);
});
fleetSelect.addEventListener("change", () => {
  if (fleetSelect.value) {
    configInput.value = fleetSelect.value;
    loadNodesForSelectedFleet().catch(handleNodeLoadError);
    updateFlashControls();
  }
});
configInput.addEventListener("input", () => {
  state.nodeLoadSeq += 1;
  resetNodeSelect("Update fleet path to load nodes");
  updateFlashControls();
});
configInput.addEventListener("change", () => {
  syncFleetSelect(configInput.value.trim());
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
$("validate-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  state.configPath = configInput.value.trim();
  state.nodeName = nodeSelect.value.trim();
  try {
    const response = await postJson("/api/validate", {
      config: state.configPath,
      node: state.nodeName,
    });
    renderNodeOptions(response.nodes || [], state.nodeName, response.node_roles || {});
    renderValidation(response);
    updateFlashControls();
  } catch (error) {
    console.error("Validation request failed", error);
    renderValidation({ ok: false, errors: [errorMessage(error)] });
  }
});

async function refreshAll() {
  try {
    await Promise.all([loadState(), loadDisks()]);
  } catch (error) {
    handleRefreshError(error);
  }
}

async function loadState() {
  try {
    const payload = await getState();
    if (!payload.ok) {
      throw new Error(errorDetail(payload) || "Could not load workspace state");
    }
    const workspace = payload.workspace || {};
    workspacePath.textContent = workspace.root || "";
    workspacePath.title = workspace.root || "";
    await renderFleets(workspace.fleet_files || [], workspace.fleets_dir || "");
    const entries = Object.entries(payload.images || {});
    imageCount.textContent = `${entries.length}`;
    images.innerHTML = entries.map(([target, image]) => imageItem(target, image)).join("");
  } catch (error) {
    console.error("State refresh failed", error);
    renderStateError(error);
  }
}

async function loadDisks() {
  try {
    const payload = await getDisks(showAllDisks.checked);
    if (!payload.ok) {
      disks.innerHTML = `<div class="inline-error">${escapeHtml((payload.errors || []).join("\n"))}</div>`;
      return;
    }
    if (!payload.disks.length) {
      disks.innerHTML = `<div class="empty-state slim"><p class="empty-title">No disks found</p><p class="empty-meta">Insert an SD card, then refresh.</p></div>`;
      state.diskDevice = "";
      updateFlashControls();
      return;
    }
    if (state.diskDevice && !payload.disks.some((disk) => disk.device === state.diskDevice)) {
      state.diskDevice = "";
    }
    disks.innerHTML = payload.disks.map((disk) => diskCard(disk, state.diskDevice)).join("");
    updateFlashControls();
  } catch (error) {
    console.error("Disk refresh failed", error);
    renderDiskError(error);
  }
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
  fleetSelect.replaceChildren();

  if (!records.length) {
    fleetSelect.disabled = true;
    fleetSelect.add(new Option("No fleet files found", ""));
    fleetEmpty.hidden = false;
    configInput.value = "";
    resetNodeSelect("No nodes available");
    updateFlashControls();
    return;
  }

  fleetEmpty.hidden = true;
  fleetSelect.disabled = false;
  for (const record of records) {
    fleetSelect.add(new Option(record.relative_path || record.name, record.path));
  }

  const current = configInput.value.trim();
  const selected = current || records[0].path;
  configInput.value = selected;
  syncFleetSelect(selected);
  await loadNodesForSelectedFleet(state.nodeName).catch(handleNodeLoadError);
  updateFlashControls();
}

function syncFleetSelect(path) {
  if (!path || fleetSelect.disabled) {
    return;
  }
  const options = Array.from(fleetSelect.options);
  if (options.some((option) => option.value === path)) {
    fleetSelect.value = path;
    return;
  }
  const custom = new Option("Custom path", path);
  custom.dataset.custom = "true";
  fleetSelect.add(custom, 0);
  fleetSelect.value = path;
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
  renderNodeOptions(response.nodes || [], selectedNode, response.node_roles || {});
  if (!response.ok) {
    renderValidation(response);
  }
}

function renderNodeOptions(nodes, preferredNode = "", nodeRoles = {}) {
  const uniqueNodes = [...new Set((nodes || []).map((node) => String(node).trim()).filter(Boolean))];
  state.nodeRoles = { ...nodeRoles };
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
  nodeSelect.replaceChildren();
  nodeSelect.add(new Option(label, ""));
  nodeSelect.disabled = true;
  applyRoleDefaultSsh();
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
  return value === "auto" ? "default" : value;
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

function updateRoleDefaultSsh() {
  const role = selectedNodeRole();
  if (!role) {
    sshAutoHint.textContent = "role default";
    nodeRoleChip.hidden = true;
    return;
  }
  sshAutoHint.textContent = role === "gate" ? "on for gate" : `off for ${role}`;
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
  setStep(steps.fleet, Boolean(config));
  setStep(steps.node, Boolean(node));
  setStep(steps.disk, Boolean(state.diskDevice));
  setStep(steps.flash, state.lastFlashOk);
  if (!nativeApi) {
    return;
  }
  const ready = Boolean(config && node && state.diskDevice);
  const needsPassword = ready && isMac && !adminPasswordInput.value;
  previewFlash.disabled = !ready || state.flashBusy;
  startFlash.disabled = !ready || needsPassword || state.flashBusy;
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
}

function setBusy(busy) {
  state.flashBusy = busy;
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
    setFlashStatus("ok", "Dry run complete. No changes were made.");
    renderPlanCard(payload);
  } else {
    setFlashStatus("bad", (payload.errors || [])[0] || "Could not build the flash plan");
    if (payload.plan && Object.keys(payload.plan).length) {
      renderPlanCard(payload);
    }
  }
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
    state.lastFlashOk = true;
    appendLog("success", "Flash complete.");
    setFlashStatus("ok", `Flash complete. Insert the disk into ${payload.node || state.nodeName || "the node"} and boot.`);
  } else if (payload.canceled) {
    setFlashStatus("warn", "Flash canceled. The disk was not modified.");
  } else {
    setFlashStatus("bad", (payload.errors || [])[0] || "Flash failed");
  }
  updateFlashControls();
  updateCopyFlashLogVisibility();
}

async function getJson(url) {
  if (nativeApi && url === "/api/state") {
    return nativeApi.getState();
  }
  return fetchJson(url);
}

async function postJson(url, body) {
  if (nativeApi && url === "/api/validate") {
    return nativeApi.validate(body);
  }
  return fetchJson(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

async function fetchJson(url, options) {
  let response;
  try {
    response = await fetch(url, options);
  } catch (error) {
    throw new Error(`Request failed for ${url}: ${error.message}`);
  }

  const text = await response.text();
  let payload = {};
  if (text) {
    try {
      payload = JSON.parse(text);
    } catch (error) {
      throw new Error(`Invalid JSON from ${url}: ${error.message}`);
    }
  }

  if (!response.ok) {
    const detail = errorDetail(payload) || text;
    const suffix = detail ? ` - ${detail}` : "";
    throw new Error(`Request failed for ${url}: ${response.status} ${response.statusText}${suffix}`);
  }
  return payload;
}

function errorDetail(payload) {
  if (!payload || typeof payload !== "object") {
    return "";
  }
  if (payload.error) {
    return payload.error;
  }
  if (Array.isArray(payload.errors)) {
    return payload.errors.join(", ");
  }
  return "";
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
  fleetSelect.replaceChildren();
  fleetSelect.disabled = true;
  fleetSelect.add(new Option("Workspace unavailable", ""));
  resetNodeSelect("No nodes available");
  fleetEmpty.hidden = false;
  imageCount.textContent = "0";
  images.innerHTML = `<div class="inline-error">${escapeHtml(errorMessage(error))}</div>`;
  updateFlashControls();
}

function renderDiskError(error) {
  disks.innerHTML = `<div class="inline-error">${escapeHtml(errorMessage(error))}</div>`;
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

function errorMessage(error) {
  return error && error.message ? error.message : String(error);
}

async function getState() {
  return getJson("/api/state");
}

async function getDisks(includeAll) {
  if (nativeApi) {
    return nativeApi.getDisks(includeAll);
  }
  const suffix = includeAll ? "?all=1" : "";
  return getJson(`/api/disks${suffix}`);
}

updateRoleDefaultSsh();
updateFlashControls();
refreshAll().catch(handleRefreshError);
