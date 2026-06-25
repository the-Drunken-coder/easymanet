const path = require("node:path");

const repoRoot = path.resolve(__dirname, "../../..");
const appIconPngPath = path.join(__dirname, "assets", "easymanet-icon.png");
const nodeNamePattern = /^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$/;
const bridgeTimeoutMs = 15000;
const diagnosticsBridgeTimeoutMs = 120000;
const imageBridgeTimeoutMs = 10 * 60 * 1000;
const meshBridgeTimeoutMs = 45000;
const flashBridgeTimeoutMs = 30 * 60 * 1000;
const sshModes = new Set(["default", "enable", "disable"]);
const imageTargetPattern = /^[A-Za-z0-9][A-Za-z0-9_.-]{0,96}$/;

module.exports = {
  appIconPngPath,
  bridgeTimeoutMs,
  diagnosticsBridgeTimeoutMs,
  flashBridgeTimeoutMs,
  imageBridgeTimeoutMs,
  imageTargetPattern,
  meshBridgeTimeoutMs,
  nodeNamePattern,
  repoRoot,
  sshModes,
};
