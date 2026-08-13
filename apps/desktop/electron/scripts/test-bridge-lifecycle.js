const assert = require("node:assert/strict");
const { EventEmitter } = require("node:events");
const fs = require("node:fs");
const Module = require("node:module");
const os = require("node:os");
const path = require("node:path");

const electronRoot = path.resolve(__dirname, "..");
const bridgeProcessPath = path.join(electronRoot, "bridge-process.js");
const environmentPath = path.join(electronRoot, "environment.js");
const mainPath = path.join(electronRoot, "main.js");
const tempRoot = fs.mkdtempSync(path.join(os.tmpdir(), "easymanet-bridge-lifecycle-"));
const fixturePath = path.join(tempRoot, "inert-process-tree.js");
const fixturePids = [];

fs.writeFileSync(
  fixturePath,
  `
const { spawn } = require("node:child_process");
const fs = require("node:fs");
const pidFile = process.argv[2];
const signalFile = process.argv[3];
const childSource = (title) => \`
  const fs = require("node:fs");
  const signalFile = \${JSON.stringify(signalFile)};
  process.title = \${JSON.stringify(title)};
  process.on("SIGTERM", () => fs.appendFileSync(signalFile, \${JSON.stringify(title + ":TERM\\n")}));
  process.stdout.write("ready\\\\n");
  setInterval(() => {}, 1000);
\`;
process.title = "python";
process.on("SIGTERM", () => fs.appendFileSync(signalFile, "python:TERM\\n"));
const childStdio = ["ignore", "pipe", "ignore"];
const gzip = spawn(process.execPath, ["-e", childSource("gzip")], {stdio: childStdio});
const dd = spawn(process.execPath, ["-e", childSource("dd")], {stdio: childStdio});
let readyChildren = 0;
const markReady = () => {
  readyChildren += 1;
  if (readyChildren === 2) {
    fs.writeFileSync(pidFile, JSON.stringify({leader: process.pid, gzip: gzip.pid, dd: dd.pid}));
  }
};
gzip.stdout.once("data", markReady);
dd.stdout.once("data", markReady);
setInterval(() => {}, 1000);
`,
);

async function main() {
  if (process.platform !== "win32") {
    await testTimeoutReapsProcessTree();
    await testShutdownReapsProcessTree();
  }
  await testShutdownClosesBridgeAdmissionWhenIdle();
  await testMainClosesBridgeAdmissionBeforeQuitting();
  console.log("Electron bridge lifecycle tests passed.");
}

async function testTimeoutReapsProcessTree() {
  const pidFile = path.join(tempRoot, "timeout-pids.json");
  const bridge = loadBridgeProcess(pidFile);
  const resultPromise = bridge.runBridgeProcess([], inertHandlers(1500));
  const pids = await readPids(pidFile);
  fixturePids.push(pids);

  assert.equal(bridge.hasActiveBridgeProcesses(), true);
  const result = await resultPromise;

  assert.equal(result.ok, false);
  assert.match(result.errors[0], /timed out/);
  assertTermSignals(signalFileFor(pidFile));
  assertProcessTreeGone(pids);
  assert.equal(bridge.hasActiveBridgeProcesses(), false);
}

async function testShutdownReapsProcessTree() {
  const pidFile = path.join(tempRoot, "shutdown-pids.json");
  const bridge = loadBridgeProcess(pidFile);
  const resultPromise = bridge.runBridgeProcess([], inertHandlers(10000));
  const pids = await readPids(pidFile);
  fixturePids.push(pids);

  await bridge.shutdownActiveBridgeProcesses();
  const result = await resultPromise;

  assert.equal(result.ok, false);
  assert.match(result.errors[0], /application shutdown/);
  assertTermSignals(signalFileFor(pidFile));
  assertProcessTreeGone(pids);
  assert.equal(bridge.hasActiveBridgeProcesses(), false);
}

async function testShutdownClosesBridgeAdmissionWhenIdle() {
  const pidFile = path.join(tempRoot, "idle-pids.json");
  const bridge = loadBridgeProcess(pidFile);

  await bridge.shutdownActiveBridgeProcesses();
  const result = await bridge.runBridgeProcess([], inertHandlers(10000));

  assert.equal(result.ok, false);
  assert.match(result.errors[0], /shutting down/);
  assert.equal(fs.existsSync(pidFile), false);
}

async function testMainClosesBridgeAdmissionBeforeQuitting() {
  const app = new EventEmitter();
  let admissionClosed = false;
  let quitCalls = 0;
  let shutdownCalls = 0;
  let finishShutdown;
  const shutdown = new Promise((resolve) => {
    finishShutdown = resolve;
  });
  app.whenReady = () => new Promise(() => {});
  app.quit = () => {
    quitCalls += 1;
  };

  const originalLoad = Module._load;
  Module._load = function load(request, parent, isMain) {
    if (request === "electron") {
      return { app, BrowserWindow: { getAllWindows: () => [] } };
    }
    if (parent && parent.filename === mainPath && request === "./bridge-process") {
      return {
        shutdownActiveBridgeProcesses: () => {
          shutdownCalls += 1;
          admissionClosed = true;
          return shutdown;
        },
      };
    }
    if (parent && parent.filename === mainPath && request === "./ipc") {
      return { registerIpc: () => {} };
    }
    if (parent && parent.filename === mainPath && request === "./window") {
      return { createWindow: () => {}, setDockIcon: () => {} };
    }
    return originalLoad.call(this, request, parent, isMain);
  };
  try {
    delete require.cache[mainPath];
    require(mainPath);
  } finally {
    Module._load = originalLoad;
  }

  const firstQuit = quitEvent();
  app.emit("before-quit", firstQuit);
  assert.equal(firstQuit.prevented, true);
  assert.equal(shutdownCalls, 1);
  assert.equal(admissionClosed, true);
  assert.equal(quitCalls, 0);

  const repeatedQuit = quitEvent();
  app.emit("before-quit", repeatedQuit);
  assert.equal(repeatedQuit.prevented, true);
  assert.equal(shutdownCalls, 1);

  finishShutdown();
  await shutdown;
  await new Promise((resolve) => setImmediate(resolve));
  assert.equal(quitCalls, 1);

  const finalQuit = quitEvent();
  app.emit("before-quit", finalQuit);
  assert.equal(finalQuit.prevented, false);
}

function loadBridgeProcess(pidFile) {
  const previousEnvironment = require.cache[environmentPath];
  require.cache[environmentPath] = {
    id: environmentPath,
    filename: environmentPath,
    loaded: true,
    exports: {
      bridgeCommand: () => ({
        command: process.execPath,
        args: [fixturePath, pidFile, signalFileFor(pidFile)],
      }),
      bridgeEnv: () => ({...process.env}),
      bridgeWorkingDirectory: () => tempRoot,
    },
  };
  delete require.cache[bridgeProcessPath];
  try {
    return require(bridgeProcessPath);
  } finally {
    if (previousEnvironment) {
      require.cache[environmentPath] = previousEnvironment;
    } else {
      delete require.cache[environmentPath];
    }
  }
}

function inertHandlers(timeoutMs) {
  return {
    timeoutMs,
    terminationGraceMs: 250,
    onStdout: () => {},
    onClose: (_state, finish) => finish({ok: true}),
  };
}

async function readPids(pidFile) {
  const deadline = Date.now() + 5000;
  while (Date.now() < deadline) {
    try {
      return JSON.parse(fs.readFileSync(pidFile, "utf8"));
    } catch (_error) {
      await new Promise((resolve) => setTimeout(resolve, 20));
    }
  }
  throw new Error(`Timed out waiting for inert fixture PID file: ${pidFile}`);
}

function assertProcessTreeGone(pids) {
  for (const [name, pid] of Object.entries(pids)) {
    assert.equal(processExists(pid), false, `${name} process ${pid} survived cleanup`);
  }
}

function assertTermSignals(signalFile) {
  assert.equal(fs.existsSync(signalFile), true, `no SIGTERM was handled: ${signalFile}`);
  const signals = fs.readFileSync(signalFile, "utf8").trim().split("\n").sort();
  assert.deepEqual(signals, ["dd:TERM", "gzip:TERM", "python:TERM"]);
}

function signalFileFor(pidFile) {
  return pidFile.replace(/-pids\.json$/, "-signals.log");
}

function processExists(pid) {
  try {
    process.kill(pid, 0);
    return true;
  } catch (error) {
    if (error.code === "ESRCH") {
      return false;
    }
    throw error;
  }
}

function quitEvent() {
  return {
    prevented: false,
    preventDefault() {
      this.prevented = true;
    },
  };
}

function cleanup() {
  for (const pids of fixturePids) {
    if (pids.leader) {
      try {
        process.kill(-pids.leader, "SIGKILL");
      } catch (_error) {
        // Already reaped by the lifecycle under test.
      }
    }
    for (const pid of Object.values(pids)) {
      try {
        process.kill(pid, "SIGKILL");
      } catch (_error) {
        // Already reaped by the lifecycle under test.
      }
    }
  }
  fs.rmSync(tempRoot, {recursive: true, force: true});
}

main()
  .catch((error) => {
    console.error(error.stack || error.message || String(error));
    process.exitCode = 1;
  })
  .finally(cleanup);
