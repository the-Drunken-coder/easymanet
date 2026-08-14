const assert = require("node:assert/strict");
const fs = require("node:fs");
const Module = require("node:module");
const os = require("node:os");
const path = require("node:path");

const electronRoot = path.resolve(__dirname, "..");
const environmentPath = path.join(electronRoot, "environment.js");
const originalLoad = Module._load;
const originalEnvironment = {...process.env};
const tempRoot = fs.mkdtempSync(path.join(os.tmpdir(), "easymanet-environment-test-"));

function fakeExecutable(name) {
  const target = path.join(tempRoot, name);
  fs.writeFileSync(target, "#!/bin/sh\nexit 99\n", {mode: 0o700});
  return target;
}

try {
  Module._load = function load(request, parent, isMain) {
    if (request === "electron") {
      return {
        app: {
          isPackaged: false,
          getPath: (name) => name === "home" ? os.homedir() : tempRoot,
        },
      };
    }
    return originalLoad(request, parent, isMain);
  };

  const fakeSudo = fakeExecutable("sudo");
  const fakePython = fakeExecutable("python3");
  process.env.PATH = `${tempRoot}:${originalEnvironment.PATH || ""}`;
  process.env.EASYMANET_PYTHON = fakePython;
  process.env.VIRTUAL_ENV = tempRoot;
  process.env.PYTHONPATH = tempRoot;

  delete require.cache[environmentPath];
  const environment = require(environmentPath);
  const stage = {
    root: tempRoot,
    sourceRoots: [path.join(tempRoot, "src")],
    workspaceDir: path.join(tempRoot, "workspace"),
  };
  const bridge = environment.elevatedBridgeCommand(["state"], stage);
  const sudo = environment.sudoBridgeCommand(bridge);
  const privilegedEnv = environment.elevatedBridgeEnv(bridge.env);

  assert.notEqual(sudo.command, fakeSudo);
  assert.equal(sudo.command, "/usr/bin/sudo");
  assert.equal(sudo.args[4], "/usr/bin/env");
  assert.equal(path.isAbsolute(bridge.command), true);
  assert.notEqual(bridge.command, fakePython);
  assert.deepEqual(bridge.args.slice(0, 2), ["-I", "-c"]);
  assert.equal(privilegedEnv.PATH, "/usr/bin:/bin:/usr/sbin:/sbin");
  assert.equal(privilegedEnv.PYTHONNOUSERSITE, "1");
  assert.equal(privilegedEnv.EASYMANET_WORKSPACE, stage.workspaceDir);
  assert.equal("EASYMANET_PYTHON" in privilegedEnv, false);
  assert.equal("VIRTUAL_ENV" in privilegedEnv, false);
  assert.equal("PYTHONPATH" in privilegedEnv, false);

  console.log("Electron elevated environment tests passed.");
} finally {
  Module._load = originalLoad;
  process.env = originalEnvironment;
  delete require.cache[environmentPath];
  fs.rmSync(tempRoot, {recursive: true, force: true});
}
