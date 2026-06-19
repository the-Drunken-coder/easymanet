const path = require("node:path");

const repoRoot = path.resolve(__dirname, "../../..");
const appIconPngPath = path.join(__dirname, "assets", "easymanet-icon.png");
const nodeNamePattern = /^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$/;
const bridgeTimeoutMs = 15000;
const meshBridgeTimeoutMs = 45000;
const flashBridgeTimeoutMs = 30 * 60 * 1000;
const sshModes = new Set(["default", "enable", "disable"]);

module.exports = {
  appIconPngPath,
  bridgeTimeoutMs,
  flashBridgeTimeoutMs,
  meshBridgeTimeoutMs,
  nodeNamePattern,
  repoRoot,
  sshModes,
};
