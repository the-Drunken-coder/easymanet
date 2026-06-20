const { app } = require("electron");
const { booleanFlag } = require("./util");
const { nodeNamePattern, sshModes } = require("./constants");
const { hasTraversalSegment, resolveConfigPath } = require("./path-utils");
const { runBridge } = require("./bridge-process");

async function validatePayload(payload) {
  if (!payload || typeof payload !== "object" || Array.isArray(payload)) {
    return { ok: false, errors: ["Validation payload must be an object"] };
  }

  const config = typeof payload.config === "string" ? payload.config.trim() : "";
  if (!config) {
    return { ok: false, errors: ["Fleet config path is required"] };
  }
  if (hasTraversalSegment(config)) {
    return { ok: false, errors: ["Fleet config path must not contain traversal segments"] };
  }

  const node = typeof payload.node === "string" ? payload.node.trim() : "";
  if (node && !nodeNamePattern.test(node)) {
    return { ok: false, errors: ["Node name contains unsupported characters"] };
  }

  const resolved = await resolveConfigPath(config, {
    runBridge,
    homeDir: () => app.getPath("home"),
  });
  if (!resolved.ok) {
    return resolved;
  }
  return { ok: true, config: resolved.config, node };
}

async function validateFlashPayload(payload) {
  const validated = await validatePayload(payload);
  if (!validated.ok) {
    return validated;
  }
  if (!validated.node) {
    return { ok: false, errors: ["Node name is required"] };
  }

  const device = typeof payload.device === "string" ? payload.device.trim() : "";
  if (!device) {
    return { ok: false, errors: ["Disk device is required"] };
  }

  const sshMode = typeof payload.sshMode === "string" ? payload.sshMode.trim() : "default";
  if (!sshModes.has(sshMode)) {
    return { ok: false, errors: ["Unsupported SSH mode"] };
  }

  const adminPassword = typeof payload.adminPassword === "string" ? payload.adminPassword : "";

  return { ...validated, device, sshMode, adminPassword };
}

async function validateMeshPayload(payload) {
  if (!payload || typeof payload !== "object" || Array.isArray(payload)) {
    return { ok: false, errors: ["Mesh discovery payload must be an object"] };
  }

  const rawConfig = typeof payload.config === "string" ? payload.config.trim() : "";
  let config = "";
  if (rawConfig) {
    if (hasTraversalSegment(rawConfig)) {
      return { ok: false, errors: ["Fleet config path must not contain traversal segments"] };
    }
    const resolved = await resolveConfigPath(rawConfig, {
      runBridge,
      homeDir: () => app.getPath("home"),
    });
    if (!resolved.ok) {
      return resolved;
    }
    config = resolved.config;
  }

  return {
    ok: true,
    config,
    scanSubnet: booleanFlag(payload.scanSubnet) || booleanFlag(payload.scan_subnet),
  };
}

async function validateDiagnosticsPayload(payload) {
  if (!payload || typeof payload !== "object" || Array.isArray(payload)) {
    return { ok: false, errors: ["Diagnostics payload must be an object"] };
  }

  const rawConfig = typeof payload.config === "string" ? payload.config.trim() : "";
  if (!rawConfig) {
    return { ok: true, config: "" };
  }
  if (hasTraversalSegment(rawConfig)) {
    return { ok: false, errors: ["Fleet config path must not contain traversal segments"] };
  }
  const resolved = await resolveConfigPath(rawConfig, {
    runBridge,
    homeDir: () => app.getPath("home"),
  });
  if (!resolved.ok) {
    return resolved;
  }
  return { ok: true, config: resolved.config };
}

function validateBootReportImportPayload(payload) {
  if (!payload || typeof payload !== "object" || Array.isArray(payload)) {
    return { ok: false, errors: ["Boot report import payload must be an object"] };
  }
  const source = typeof payload.source === "string" ? payload.source.trim() : "";
  if (!source) {
    return { ok: false, errors: ["Boot report source path is required"] };
  }
  if (hasTraversalSegment(source)) {
    return { ok: false, errors: ["Boot report source path must not contain traversal segments"] };
  }
  return { ok: true, source };
}

function flashArgs(payload) {
  const args = ["--config", payload.config, "--node", payload.node, "--device", payload.device];
  if (payload.sshMode === "enable") {
    args.push("--enable-ssh");
  } else if (payload.sshMode === "disable") {
    args.push("--disable-ssh");
  }
  return args;
}

module.exports = {
  flashArgs,
  validateBootReportImportPayload,
  validateDiagnosticsPayload,
  validateFlashPayload,
  validateMeshPayload,
  validatePayload,
};
