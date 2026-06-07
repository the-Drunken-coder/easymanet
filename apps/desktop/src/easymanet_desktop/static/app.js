const state = {
  configPath: "",
  nodeName: "",
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
const showAllDisks = document.getElementById("show-all-disks");
const chooseConfig = document.getElementById("choose-config");
const openFleetsFolder = document.getElementById("open-fleets-folder");
const nativeApi = window.easymanet || null;

if (!nativeApi) {
  chooseConfig.hidden = true;
  openFleetsFolder.hidden = true;
}

document.getElementById("refresh").addEventListener("click", () => refreshAll());
fleetSelect.addEventListener("change", () => {
  if (fleetSelect.value) {
    configInput.value = fleetSelect.value;
  }
});
chooseConfig.addEventListener("click", async () => {
  if (!nativeApi) {
    return;
  }
  const result = await nativeApi.chooseConfig();
  if (result.ok && result.path) {
    configInput.value = result.path;
    syncFleetSelect(result.path);
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
showAllDisks.addEventListener("change", () => loadDisks());
document.getElementById("validate-form").addEventListener("submit", async event => {
  event.preventDefault();
  state.configPath = configInput.value.trim();
  state.nodeName = document.getElementById("node-name").value.trim();
  const response = await postJson("/api/validate", {
    config: state.configPath,
    node: state.nodeName,
  });
  renderValidation(response);
});

async function refreshAll() {
  await Promise.all([loadState(), loadDisks()]);
}

async function loadState() {
  const payload = await getState();
  const workspace = payload.workspace || {};
  workspacePath.textContent = workspace.root ? `Workspace: ${workspace.root}` : "";
  renderFleets(workspace.fleet_files || [], workspace.fleets_dir || "");
  const entries = Object.entries(payload.images || {});
  imageCount.textContent = `${entries.length}`;
  images.innerHTML = entries.map(([target, image]) => imageMarkup(target, image)).join("");
}

async function loadDisks() {
  const payload = await getDisks(showAllDisks.checked);
  if (!payload.ok) {
    disks.innerHTML = `<div class="status-bad">${escapeHtml((payload.errors || []).join("\n"))}</div>`;
    return;
  }
  if (!payload.disks.length) {
    disks.innerHTML = `<div class="meta">No disks found.</div>`;
    return;
  }
  disks.innerHTML = payload.disks.map(diskMarkup).join("");
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
  return `
    <div class="item">
      <div class="name">${escapeHtml(disk.device)}</div>
      <div class="meta">${escapeHtml(disk.model || "")}</div>
      <div class="meta">${escapeHtml(disk.size_human || "")} - ${disk.removable ? "removable" : "fixed"}</div>
      <div class="meta">${escapeHtml((disk.mounted || []).join(", ") || "not mounted")}</div>
      ${warnings}
    </div>
  `;
}

async function getJson(url) {
  if (nativeApi && url === "/api/state") {
    return nativeApi.getState();
  }
  const response = await fetch(url);
  return response.json();
}

async function postJson(url, body) {
  if (nativeApi && url === "/api/validate") {
    return nativeApi.validate(body);
  }
  const response = await fetch(url, {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify(body),
  });
  return response.json();
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

refreshAll();
