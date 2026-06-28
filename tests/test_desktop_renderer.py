import json
from pathlib import Path
import shutil
import subprocess

import pytest


def test_desktop_renderer_state_flows_use_bridge_payloads():
    """Exercise desktop renderer state transitions wired through bridge payloads."""
    root = Path(__file__).resolve().parents[1]
    static = root / "apps" / "desktop" / "src" / "easymanet_desktop" / "static"
    scripts = [
        static / name
        for name in (
            "render.js",
            "state.js",
            "api.js",
            "fleet.js",
            "disk.js",
            "flash-ui.js",
            "mesh.js",
            "diagnostics.js",
            "app.js",
        )
    ]
    script = """
const fs = require("node:fs");
const vm = require("node:vm");

function makeClassList(element) {
  const values = new Set();
  return {
    toggle(name, force) {
      const enabled = force === undefined ? !values.has(name) : Boolean(force);
      if (enabled) {
        values.add(name);
      } else {
        values.delete(name);
      }
      element.className = Array.from(values).join(" ");
      return enabled;
    },
    add(name) {
      values.add(name);
      element.className = Array.from(values).join(" ");
    },
    remove(name) {
      values.delete(name);
      element.className = Array.from(values).join(" ");
    },
    contains(name) {
      return values.has(name);
    },
  };
}

function makeElement(id = "") {
  const element = {
    id,
    hidden: false,
    disabled: false,
    checked: false,
    textContent: "",
    innerHTML: "",
    value: "",
    className: "",
    dataset: {},
    style: {},
    attributes: {},
    options: [],
    children: [],
    listeners: {},
    scrollHeight: 0,
    scrollTop: 0,
    clientHeight: 100,
    get childElementCount() {
      return this.children.filter((child) => child && typeof child === "object").length;
    },
    addEventListener(type, callback) {
      this.listeners[type] = callback;
    },
    replaceChildren(...children) {
      this.children = children;
      this.options = [];
    },
    add(option, index) {
      if (index === undefined) {
        this.options.push(option);
      } else {
        this.options.splice(index, 0, option);
      }
    },
    append(...children) {
      this.children.push(...children);
    },
    appendChild(child) {
      this.children.push(child);
      return child;
    },
    setAttribute(name, value) {
      this.attributes[name] = String(value);
    },
    removeAttribute(name) {
      delete this.attributes[name];
    },
    getAttribute(name) {
      return this.attributes[name] || null;
    },
    closest() {
      return null;
    },
  };
  element.classList = makeClassList(element);
  return element;
}

function textTree(root) {
  const childText = root.children.map((child) => textTree(child)).join("");
  return `${root.textContent || ""}${childText}`;
}

function htmlTree(root) {
  const childHtml = root.children.map((child) => htmlTree(child)).join("");
  return `${root.innerHTML || ""}${childHtml}`;
}

const elements = {};
function element(id) {
  if (!elements[id]) {
    elements[id] = makeElement(id);
  }
  return elements[id];
}

const radioAuto = element("role-default-ssh");
const radioEnable = element("ssh-enable");
const radioDisable = element("ssh-disable");
radioAuto.checked = true;
radioAuto.value = "auto";
radioEnable.value = "enable";
radioDisable.value = "disable";
element("mesh-scan-subnet").checked = true;

let stateCalls = 0;
let imageUpdateCalls = 0;
let imageInstallCalls = 0;
let imageInstalled = false;
let imageUpdateChecks = [];
let holdImageUpdates = false;
let imageUpdateResolvers = [];
let holdState = false;
let stateResolvers = [];
let holdMesh = false;
let resolveMesh = null;
let flashCallback = null;
let copiedTexts = [];
let diagnosticsCalls = [];

function statePayload() {
  return {
    ok: true,
    workspace: {
      root: "/tmp/EasyMANET",
      fleets_dir: "/tmp/EasyMANET/Fleets",
      fleet_files: [{ name: "field.yml", relative_path: "field.yml", path: "/tmp/EasyMANET/Fleets/field.yml" }],
    },
    images: {
      "rpi4-mm6108-spi": stateCalls > 1
        ? { cached_path: "/tmp/openmanet.img.gz", version: imageInstalled ? "images-v0.2.7" : "images-v0.2.6" }
        : {},
    },
  };
}

const nativeApi = {
  onFlashEvent(callback) {
    flashCallback = callback;
  },
  getState() {
    stateCalls += 1;
    const payload = statePayload();
    if (holdState) {
      return new Promise((resolve) => stateResolvers.push(() => resolve(payload)));
    }
    return Promise.resolve(payload);
  },
  getImageUpdates(options = {}) {
    imageUpdateCalls += 1;
    imageUpdateChecks.push(Boolean(options.checkLatest));
    const payload = {
      ok: true,
      updates: {
        "rpi4-mm6108-spi": {
          status: imageInstalled ? "current" : "outdated",
          update_available: !imageInstalled,
          current_version: imageInstalled ? "images-v0.2.7" : "images-v0.2.6",
          latest_version: "images-v0.2.7",
          latest_sha256: "b".repeat(64),
        },
      },
    };
    if (holdImageUpdates) {
      return new Promise((resolve) => {
        imageUpdateResolvers.push(() => resolve(payload));
      });
    }
    return Promise.resolve(payload);
  },
  installImageUpdate(target) {
    imageInstallCalls += 1;
    imageInstalled = target === "rpi4-mm6108-spi";
    return Promise.resolve({
      ok: true,
      installed: true,
      target,
      version: "images-v0.2.7",
      image: { cached_path: "/tmp/openmanet.img.gz", version: "images-v0.2.7" },
      update: {
        status: "current",
        update_available: false,
        current_version: "images-v0.2.7",
        latest_version: "images-v0.2.7",
      },
    });
  },
  getDisks() {
    return Promise.resolve({ ok: true, disks: [] });
  },
  validate() {
    return Promise.resolve({
      ok: true,
      nodes: ["gate01"],
      node_roles: { gate01: "gate" },
      node_access: { gate01: { management_ip: "10.41.254.9" } },
    });
  },
  discoverMesh() {
    if (holdMesh) {
      return new Promise((resolve) => {
        resolveMesh = resolve;
      });
    }
    return Promise.resolve({ ok: true, nodes: [], links: [], candidates_checked: 0 });
  },
  runDiagnostics(body) {
    diagnosticsCalls.push(body);
    return Promise.resolve({ ok: true, summary: "diagnostics summary", support_code: "ready" });
  },
  chooseConfig() {
    return Promise.resolve({ ok: true, path: "" });
  },
  openFleetsFolder() {
    return Promise.resolve({ ok: true });
  },
  flashPlan() {
    return Promise.resolve({ ok: true });
  },
  flash() {
    return Promise.resolve({ ok: true });
  },
  copyText(text) {
    copiedTexts.push(text);
    return Promise.resolve({ ok: true });
  },
};

const context = {
  console,
  setTimeout,
  clearTimeout,
  setInterval: () => 1,
  clearInterval: () => {},
  Option: function Option(text, value) {
    return { text, textContent: text, value, dataset: {} };
  },
  window: {
    navigator: { platform: "MacIntel" },
    easymanet: nativeApi,
    addEventListener() {},
  },
  document: {
    body: makeElement("body"),
    hidden: false,
    getElementById: element,
    createElement: () => makeElement(),
    addEventListener() {},
    querySelector(selector) {
      if (selector === "input[name='ssh-mode']:checked") {
        return [radioAuto, radioEnable, radioDisable].find((radio) => radio.checked) || null;
      }
      return null;
    },
    querySelectorAll(selector) {
      if (selector === "input[name='ssh-mode']") {
        return [radioAuto, radioEnable, radioDisable];
      }
      return [];
    },
  },
};
context.globalThis = context;
vm.createContext(context);
for (const scriptPath of process.argv.slice(1)) {
  vm.runInContext(fs.readFileSync(scriptPath, "utf8"), context);
}

const flush = () => new Promise((resolve) => setTimeout(resolve, 0));

(async () => {
  await flush();
  await flush();
  await flush();
  await flush();

  const startupImageUpdateChecked = imageUpdateCalls > 0;
  const startupImageUpdateNotice = element("images").innerHTML.includes("new image available: images-v0.2.7");
  const startupImageUpdateButton = element("images").innerHTML.includes("Install Update")
    && element("images").innerHTML.includes("data-image-install-target");
  element("check-image-updates").listeners.click();
  await flush();
  await flush();
  await flush();
  const explicitImageUpdateChecked = imageUpdateCalls === 2
    && imageUpdateChecks[0] === true
    && imageUpdateChecks[1] === true;
  const explicitImageUpdateNotice = element("images").innerHTML.includes("new image available: images-v0.2.7");
  const explicitImageUpdateButton = element("images").innerHTML.includes("Install Update")
    && element("images").innerHTML.includes("data-image-install-target");
  holdImageUpdates = true;
  element("check-image-updates").listeners.click();
  await flush();
  const firstCheckShowsBusy = element("check-image-updates").disabled === true
    && element("check-image-updates").textContent === "Checking...";
  const newerImageUpdateCheck = context.refreshImageUpdateStatus({ checkLatest: true });
  await flush();
  const secondCheckShowsBusy = element("check-image-updates").disabled === true
    && element("check-image-updates").textContent === "Checking...";
  imageUpdateResolvers.shift()();
  await flush();
  await flush();
  const staleCheckDoesNotEnableButton = element("check-image-updates").disabled === true
    && element("check-image-updates").textContent === "Checking...";
  holdImageUpdates = false;
  imageUpdateResolvers.shift()();
  await newerImageUpdateCheck;
  await flush();
  const latestCheckRestoresButton = element("check-image-updates").disabled === false
    && element("check-image-updates").textContent === "Check Updates";
  const overlappingImageUpdateButtonSequenced = firstCheckShowsBusy
    && secondCheckShowsBusy
    && staleCheckDoesNotEnableButton
    && latestCheckRestoresButton;
  context.window.EMState.images = {
    "rpi4-mm6108-spi": { cached_path: "/tmp/openmanet.img.gz", version: "images-v0.2.6" },
    "rpi4-mm6108-spi-alt": { cached_path: "/tmp/openmanet-alt.img.gz", version: "images-v0.2.6" },
  };
  context.window.EMState.imageUpdates = {
    "rpi4-mm6108-spi": { status: "outdated", update_available: true, latest_version: "images-v0.2.7" },
    "rpi4-mm6108-spi-alt": { status: "outdated", update_available: true, latest_version: "images-v0.2.7" },
  };
  context.window.EMState.imageInstallTarget = "rpi4-mm6108-spi";
  context.renderImageState(context.window.EMState.images);
  const imageHtml = element("images").innerHTML;
  const otherTargetMarker = imageHtml.includes('data-image-install-target="rpi4-mm6108-spi-alt"');
  const otherImageInstallDisabled = otherTargetMarker
    && /data-image-install-target="rpi4-mm6108-spi-alt"[^>]*disabled/.test(imageHtml);
  context.window.EMState.imageInstallTarget = "";
  const meshFleetDropdownPopulated = element("mesh-config-source").options.some((option) => option.value === "/tmp/EasyMANET/Fleets/field.yml")
    && element("mesh-config-source").value === "/tmp/EasyMANET/Fleets/field.yml";
  element("mesh-config-source").value = "/tmp/EasyMANET/Fleets/field.yml";
  element("mesh-config-source").listeners.change();
  await flush();
  await flush();
  const meshFleetDropdownSyncsConfig = element("config-path").value === "/tmp/EasyMANET/Fleets/field.yml"
    && element("fleet-select").value === "/tmp/EasyMANET/Fleets/field.yml";

  await context.installImageUpdate("rpi4-mm6108-spi");
  await flush();
  await flush();
  await flush();
  const imageInstallTriggered = imageInstallCalls === 1;
  const imageInstallClearsNotice = !element("images").innerHTML.includes("new image available: images-v0.2.7");
  const imageInstallUpdateStored = context.window.EMState.imageUpdates["rpi4-mm6108-spi"].status === "current"
    && context.window.EMState.imageUpdates["rpi4-mm6108-spi"].update_available === false;

  const beforeDownload = stateCalls;
  context.renderFlashEvent({ event_type: "download_completed" });
  await flush();
  await flush();
  const downloadCompletedRefreshesImages = stateCalls > beforeDownload;

  holdState = true;
  const beforeQueued = stateCalls;
  context.renderFlashEvent({ event_type: "download_completed" });
  context.renderFlashEvent({ event_type: "download_completed" });
  await flush();
  const queuedCoalesced = stateCalls === beforeQueued + 1;
  stateResolvers.shift()();
  await flush();
  await flush();
  const queuedStarted = stateCalls === beforeQueued + 2;
  holdState = false;
  stateResolvers.shift()();
  await flush();
  await flush();

  holdState = true;
  const beforeQueuedCheckLatest = imageUpdateCalls;
  context.refreshImageSidebar();
  context.refreshImageSidebar({ checkLatest: true });
  await flush();
  stateResolvers.shift()();
  await flush();
  await flush();
  holdState = false;
  stateResolvers.shift()();
  await flush();
  await flush();
  const queuedCheckLatestPreserved = imageUpdateCalls === beforeQueuedCheckLatest + 1
    && imageUpdateChecks[imageUpdateChecks.length - 1] === true;

  context.resetConsole();
  context.clearPlan();
  element("flash-status").hidden = true;
  element("flash-status-text").textContent = "";
  context.renderFlash({ ok: false, canceled: true, warnings: [], errors: [] });
  const statusOnlyOutputActivatesLayout = element("flash-panel").classList.contains("has-output")
    && element("console-wrap").hidden === true;
  context.clearPlan();
  element("flash-status").hidden = true;
  element("flash-status-text").textContent = "";
  element("flash-progress").hidden = true;
  element("progress-text").textContent = "";
  context.renderPlanCard({
    plan: {
      node: "<img src=x onerror=alert(1)>",
      device: "/dev/disk-test",
      boot_payload: "<boot>",
    },
    provision_display: "<script>alert(1)</script>",
    dry_run_info: "<b>boot files</b>",
  });
  const planText = textTree(element("flash-plan"));
  const planHtml = htmlTree(element("flash-plan"));
  const planPayloadTextOnly = element("flash-panel").classList.contains("has-output")
    && planText.includes("<img src=x onerror=alert(1)>")
    && planText.includes("<script>alert(1)</script>")
    && planText.includes("<boot>")
    && planText.includes("<b>boot files</b>")
    && !planHtml.includes("<img src=x")
    && !planHtml.includes("<script>")
    && !planHtml.includes("<boot>")
    && !planHtml.includes("<b>boot files</b>");
  context.renderFlash({ ok: true, node: "gate01", plan: { ssh: "no textual", ssh_enabled: true } });
  const sshEnabledHint = context.window.EMState.logLines.some((line) => line.includes("SSH to root@"));
  context.renderFlash({ ok: true, node: "gate01", plan: { ssh: "yes textual", ssh_enabled: false } });
  const sshDisabledHint = !element("flash-status-text").textContent.includes("SSH to root@")
    && context.window.EMState.logLines.some((line) =>
      line.includes("Connect Ethernet to the node management port.")
    );

  holdMesh = true;
  const meshPromise = context.discoverMesh();
  const meshBusy = element("mesh-discover").textContent === "Scanning..."
    && element("mesh-discover").disabled === true
    && element("mesh-scanning").hidden === false
    && element("mesh-radios").attributes["aria-busy"] === "true";
  resolveMesh({ ok: true, nodes: [], links: [], candidates_checked: 0 });
  await meshPromise;
  const meshRestored = element("mesh-discover").textContent === "Scan Mesh"
    && element("mesh-discover").disabled === false
    && element("mesh-scanning").hidden === true
    && !("aria-busy" in element("mesh-radios").attributes);
  const meshLogAvailable = element("copy-mesh-log").disabled === false
    && context.window.EMState.meshLogLines.some((line) => line.includes("Scan started."))
    && context.window.EMState.meshLogLines.some((line) => line.includes("Scan complete: 0 nodes"));
  await element("copy-mesh-log").listeners.click();
  const meshLogCopied = copiedTexts.some((text) => text.includes("Scan started.") && text.includes("Scan complete: 0 nodes"));

  await element("diagnostics-form").listeners.submit({ preventDefault() {} });
  await flush();
  await flush();
  const diagnosticsRunUsesSelectedFleet = diagnosticsCalls.length === 1
    && diagnosticsCalls[0].config === "/tmp/EasyMANET/Fleets/field.yml";
  const diagnosticsOutputRendered = element("diagnostics-output").textContent === "diagnostics summary"
    && element("diagnostics-result").textContent === "ready";
  await element("diagnostics-copy").listeners.click();
  const diagnosticsSummaryCopied = copiedTexts.includes("diagnostics summary");

  process.stdout.write(JSON.stringify({
    registeredFlashCallback: typeof flashCallback === "function",
    startupImageUpdateChecked,
    startupImageUpdateNotice,
    startupImageUpdateButton,
    explicitImageUpdateChecked,
    explicitImageUpdateNotice,
    explicitImageUpdateButton,
    overlappingImageUpdateButtonSequenced,
    otherImageInstallDisabled,
    meshFleetDropdownPopulated,
    meshFleetDropdownSyncsConfig,
    imageInstallTriggered,
    imageInstallClearsNotice,
    imageInstallUpdateStored,
    downloadCompletedRefreshesImages,
    queuedCoalesced,
    queuedStarted,
    queuedCheckLatestPreserved,
    statusOnlyOutputActivatesLayout,
    planPayloadTextOnly,
    sshEnabledHint,
    sshDisabledHint,
    meshBusy,
    meshRestored,
    meshLogAvailable,
    meshLogCopied,
    diagnosticsRunUsesSelectedFleet,
    diagnosticsOutputRendered,
    diagnosticsSummaryCopied,
  }));
})().catch((error) => {
  console.error(error);
  process.exit(1);
});
"""
    node_exe = shutil.which("node")
    if not node_exe:
        pytest.skip("Node.js is required for desktop renderer VM tests")

    result = subprocess.run(  # noqa: S603 - fixed executable and repo-local script inputs
        [node_exe, "-e", script, *map(str, scripts)],
        capture_output=True,
        check=True,
        text=True,
        timeout=30,
    )
    payload = json.loads(result.stdout)

    assert payload == {
        "registeredFlashCallback": True,
        "startupImageUpdateChecked": True,
        "startupImageUpdateNotice": True,
        "startupImageUpdateButton": True,
        "explicitImageUpdateChecked": True,
        "explicitImageUpdateNotice": True,
        "explicitImageUpdateButton": True,
        "overlappingImageUpdateButtonSequenced": True,
        "otherImageInstallDisabled": True,
        "meshFleetDropdownPopulated": True,
        "meshFleetDropdownSyncsConfig": True,
        "imageInstallTriggered": True,
        "imageInstallClearsNotice": True,
        "imageInstallUpdateStored": True,
        "downloadCompletedRefreshesImages": True,
        "queuedCoalesced": True,
        "queuedStarted": True,
        "queuedCheckLatestPreserved": True,
        "statusOnlyOutputActivatesLayout": True,
        "planPayloadTextOnly": True,
        "sshEnabledHint": True,
        "sshDisabledHint": True,
        "meshBusy": True,
        "meshRestored": True,
        "meshLogAvailable": True,
        "meshLogCopied": True,
        "diagnosticsRunUsesSelectedFleet": True,
        "diagnosticsOutputRendered": True,
        "diagnosticsSummaryCopied": True,
    }
