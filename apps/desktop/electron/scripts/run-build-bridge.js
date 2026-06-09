const { spawnSync } = require("node:child_process");
const fs = require("node:fs");
const path = require("node:path");

const candidates = [];

if (process.env.PYTHON) {
  candidates.push(process.env.PYTHON);
}
if (process.platform === "win32") {
  candidates.push("python", "py");
} else {
  candidates.push("python3", "python");
}

for (const candidate of candidates) {
  if ((path.isAbsolute(candidate) || candidate.includes(path.sep)) && !fs.existsSync(candidate)) {
    continue;
  }
  const args = candidate === "py" ? ["-3", "scripts/build-bridge.py"] : ["scripts/build-bridge.py"];
  const result = spawnSync(candidate, args, { stdio: "inherit" });
  if (!result.error) {
    process.exit(result.status ?? 0);
  }
}

console.error("Could not find a usable Python interpreter for scripts/build-bridge.py");
process.exit(1);
