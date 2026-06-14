const state = {
  configPath: "",
  nodeName: "",
  diskDevice: "",
  sudoCommand: "",
};

const workspacePath = document.getElementById("workspace-path");
const fleetFolder = document.getElementById("fleet-folder");
const fleetEmpty = document.getElementById("fleet-empty");
const fleetEmptyPath = document.getElementById("fleet-empty-path");
const fleetCount = document.getElementById("fleet-count");
const fleetSelect = document.getElementById("fleet-select");
const configInput = document.getElementById("config-path");
const imageCount = document.getElementById("image-count");
const images = document.getElementById("images");
const disks = document.getElementById("disks");
const validationOutput = document.getElementById("validation-output");
const flashPanel = document.getElementById("flash-panel");
const flashReady = document.getElementById("flash-ready");
const selectedDisk = document.getElementById("selected-disk");
const previewFlash = document.getElementById("preview-flash");
const startFlash = document.getElementById("start-flash");
const flashOutput = document.getElementById("flash-output");
const copySudo = document.getElementById("copy-sudo");
const showAllDisks = document.getElementById("show-all-disks");
const chooseConfig = document.getElementById("choose-config");
const openFleetsFolder = document.getElementById("open-fleets-folder");
const nativeApi = window.easymanet || null;

if (!nativeApi) {
  chooseConfig.hidden = true;
  openFleetsFolder.hidden = true;
  flashPanel.hidden = true;
} else if (nativeApi.onFlashEvent) {
  nativeApi.onFlashEvent(renderFlashEvent);
}

document.getElementById("refresh").addEventListener("click", () => {
  refreshAll().catch(handleRefreshError);
});
fleetSelect.addEventListener("change", () => {
  if (fleetSelect.value) {
    configInput.value = fleetSelect.value;
    updateFlashControls();
  }
});
configInput.addEventListener("input", updateFlashControls);
document.getElementById("node-name").addEventListener("input", updateFlashControls);
chooseConfig.addEventListener("click", async () => {
  if (!nativeApi) {
    return;
  }
  const result = await nativeApi.chooseConfig();
  if (result.ok && result.path) {
    configInput.value = result.path;
    syncFleetSelect(result.path);
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
disks.addEventListener("click", event => {
  const button = event.target.closest("[data-device]");
  if (!button) {
    return;
  }
  state.diskDevice = button.dataset.device || "";
  selectedDisk.textContent = state.diskDevice || "None";
  loadDisks().catch(renderDiskError);
  updateFlashControls();
});
document.querySelectorAll("input[name='ssh-mode']").forEach(input => {
  input.addEventListener("change", updateFlashControls);
});
previewFlash.addEventListener("click", async () => {
  if (!nativeApi) {
    return;
  }
  renderFlashStatus("Preparing flash preview...");
  const response = await nativeApi.flashPlan(flashPayload());
  renderFlash(response);
});
startFlash.addEventListener("click", async () => {
  if (!nativeApi) {
    return;
  }
  renderFlashStatus("Flashing selected disk...");
  const response = await nativeApi.flash(flashPayload());
  renderFlash(response);
  await loadDisks().catch(renderDiskError);
});
copySudo.addEventListener("click", async () => {
  if (!nativeApi || !state.sudoCommand) {
    return;
  }
  const result = await nativeApi.copyText(state.sudoCommand);
  if (result.ok) {
    copySudo.textContent = "Copied";
    setTimeout(() => {
      copySudo.textContent = "Copy Sudo Command";
    }, 1200);
  }
});
document.getElementById("validate-form").addEventListener("submit", async event => {
  event.preventDefault();
  state.configPath = configInput.value.trim();
  state.nodeName = document.getElementById("node-name").value.trim();
  try {
    const response = await postJson("/api/validate", {
      config: state.configPath,
      node: state.nodeName,
    });
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
    workspacePath.textContent = workspace.root ? `Workspace: ${workspace.root}` : "";
    renderFleets(workspace.fleet_files || [], workspace.fleets_dir || "");
    const entries = Object.entries(payload.images || {});
    imageCount.textContent = `${entries.length}`;
    images.innerHTML = entries.map(([target, image]) => imageMarkup(target, image)).join("");
  } catch (error) {
    console.error("State refresh failed", error);
    renderStateError(error);
  }
}

async function loadDisks() {
  try {
    const payload = await getDisks(showAllDisks.checked);
    if (!payload.ok) {
      disks.innerHTML = `<div class="status-bad">${escapeHtml((payload.errors || []).join("\n"))}</div>`;
      return;
    }
    if (!payload.disks.length) {
      disks.innerHTML = `<div class="meta">No disks found.</div>`;
      state.diskDevice = "";
      selectedDisk.textContent = "None";
      updateFlashControls();
      return;
    }
    if (state.diskDevice && !payload.disks.some(disk => disk.device === state.diskDevice)) {
      state.diskDevice = "";
      selectedDisk.textContent = "None";
    }
    disks.innerHTML = payload.disks.map(diskMarkup).join("");
    updateFlashControls();
  } catch (error) {
    console.error("Disk refresh failed", error);
    renderDiskError(error);
  }
}

function renderValidation(payload) {
  const lines = [];
  if (payload.ok) {
    lines.push("valid");
  }
  for (const error of payload.errors || []) {
    lines.push(`error: ${error}`);
  }
  for (const warning of payload.warnings || []) {
    lines.push(`warning: ${warning}`);
  }
  if ((payload.nodes || []).length) {
    lines.push(`nodes: ${payload.nodes.join(", ")}`);
  }
  validationOutput.textContent = lines.join("\n") || "no result";
  validationOutput.className = payload.ok ? "status-ok" : "status-bad";
}

function renderFleets(records, folder) {
  fleetFolder.textContent = folder ? `Fleets: ${folder}` : "";
  fleetEmptyPath.textContent = folder || "";
  fleetCount.textContent = `${records.length}`;
  fleetSelect.replaceChildren();

  if (!records.length) {
    fleetSelect.disabled = true;
    fleetSelect.add(new Option("No fleet files found", ""));
    fleetEmpty.hidden = false;
    configInput.value = "";
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
  updateFlashControls();
}

function syncFleetSelect(path) {
  if (!path || fleetSelect.disabled) {
    return;
  }
  const options = Array.from(fleetSelect.options);
  if (options.some(option => option.value === path)) {
    fleetSelect.value = path;
    return;
  }
  const custom = new Option("Custom path", path);
  custom.dataset.custom = "true";
  fleetSelect.add(custom, 0);
  fleetSelect.value = path;
}

function imageMarkup(target, image) {
  const cached = image.cached_path ? `<div class="status-ok">cached</div>` : `<div class="status-warn">not cached</div>`;
  const version = image.version || "unversioned";
  const sha = image.sha256 || "";
  return `
    <div class="item">
      <div class="name">${escapeHtml(target)}</div>
      <div class="meta">${escapeHtml(version)}</div>
      <div class="meta">${escapeHtml(image.url || "")}</div>
      <div class="meta">${escapeHtml(sha)}</div>
      ${cached}
    </div>
  `;
}

function diskMarkup(disk) {
  const warnings = (disk.warnings || []).map(item => `<div class="status-bad">${escapeHtml(item)}</div>`).join("");
  const selected = disk.device === state.diskDevice;
  return `
    <div class="item selectable${selected ? " selected" : ""}">
      <div>
        <div class="name">${escapeHtml(disk.device)}</div>
        <div class="meta">${escapeHtml(disk.model || "")}</div>
        <div class="meta">${escapeHtml(disk.size_human || "")} - ${disk.removable ? "removable" : "fixed"}</div>
        <div class="meta">${escapeHtml((disk.mounted || []).join(", ") || "not mounted")}</div>
        ${warnings}
      </div>
      <button type="button" data-device="${escapeHtml(disk.device)}">${selected ? "Selected" : "Select"}</button>
    </div>
  `;
}

function flashPayload() {
  state.configPath = configInput.value.trim();
  state.nodeName = document.getElementById("node-name").value.trim();
  return {
    config: state.configPath,
    node: state.nodeName,
    device: state.diskDevice,
    sshMode: selectedSshMode(),
  };
}

function selectedSshMode() {
  return document.querySelector("input[name='ssh-mode']:checked")?.value || "default";
}

function updateFlashControls() {
  if (!nativeApi) {
    return;
  }
  const config = configInput.value.trim();
  const node = document.getElementById("node-name").value.trim();
  const ready = Boolean(config && node && state.diskDevice);
  previewFlash.disabled = !ready;
  startFlash.disabled = !ready;
  flashReady.textContent = ready ? "ready" : "needs config, node, disk";
}

function renderFlashStatus(message) {
  state.sudoCommand = "";
  copySudo.hidden = true;
  copySudo.textContent = "Copy Sudo Command";
  flashOutput.className = "";
  flashOutput.textContent = message;
}

function renderFlashEvent(event) {
  if (!event || !event.message) {
    return;
  }
  const prefix = event.level === "warning" ? "warning: " : event.level === "error" ? "error: " : "";
  const current = flashOutput.textContent.trim();
  const next = `${prefix}${event.message}`;
  flashOutput.textContent = current ? `${current}\n${next}` : next;
  if (event.level === "warning") {
    flashOutput.className = "status-warn";
  } else if (event.level === "error") {
    flashOutput.className = "status-bad";
  }
}

function renderFlash(payload) {
  state.sudoCommand = payload.sudo_command || "";
  copySudo.hidden = !state.sudoCommand;
  const lines = [];
  if (payload.ok) {
    lines.push("ok");
  }
  if (payload.canceled) {
    lines.push("canceled");
  }
  for (const error of payload.errors || []) {
    lines.push(`error: ${error}`);
  }
  for (const warning of payload.warnings || []) {
    lines.push(`warning: ${warning}`);
  }
  if (payload.image?.cached_path) {
    lines.push(`image: ${payload.image.cached_path}`);
  } else if (payload.image?.url) {
    lines.push(`image: ${payload.image.url}`);
  }
  if (payload.output) {
    lines.push("");
    lines.push(payload.output);
  }
  if (state.sudoCommand) {
    lines.push("");
    lines.push("sudo:");
    lines.push(state.sudoCommand);
  }
  flashOutput.textContent = lines.join("\n") || "no result";
  flashOutput.className = payload.ok ? "status-ok" : "status-bad";
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
    headers: {"Content-Type": "application/json"},
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
  fleetEmpty.hidden = false;
  imageCount.textContent = "0";
  images.innerHTML = `<div class="status-bad">${escapeHtml(errorMessage(error))}</div>`;
  updateFlashControls();
}

function renderDiskError(error) {
  disks.innerHTML = `<div class="status-bad">${escapeHtml(errorMessage(error))}</div>`;
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

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

refreshAll().catch(handleRefreshError);
