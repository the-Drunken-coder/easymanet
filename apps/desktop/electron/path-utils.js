const path = require("node:path");

async function resolveConfigPath(config, { runBridge, homeDir }) {
  const expanded = expandHome(config, homeDir);
  if (path.isAbsolute(expanded)) {
    return resolveConfigWithBridge(expanded, runBridge);
  }

  const state = await runBridge(["state"]);
  if (!state.ok || !state.workspace || !state.workspace.fleets_dir) {
    return { ok: false, errors: state.errors || ["Fleets folder is unavailable"] };
  }
  const fleetRoot = path.resolve(state.workspace.fleets_dir);
  const candidate = path.resolve(fleetRoot, expanded);
  if (!isInside(fleetRoot, candidate)) {
    return { ok: false, errors: ["Fleet config path must stay inside the Fleets folder"] };
  }
  return resolveConfigWithBridge(candidate, runBridge);
}

async function resolveConfigWithBridge(configPath, runBridge) {
  const payload = await runBridge(["resolve-config", "--config", path.resolve(configPath)]);
  if (!payload.ok) {
    return payload;
  }
  return { ok: true, config: payload.config_path };
}

function expandHome(value, homeDir) {
  if (value === "~") {
    return homeDir();
  }
  if (value.startsWith(`~${path.sep}`) || value.startsWith("~/") || value.startsWith("~\\")) {
    return path.join(homeDir(), value.slice(2));
  }
  return value;
}

function hasTraversalSegment(value) {
  return value.split(/[\\/]+/).some((part) => part === "..");
}

function isInside(root, candidate) {
  const relative = path.relative(root, candidate);
  return Boolean(relative) && !relative.startsWith("..") && !path.isAbsolute(relative);
}

module.exports = {
  hasTraversalSegment,
  isInside,
  resolveConfigPath,
};
