const { spawn } = require("node:child_process");
const { bridgeTimeoutMs, flashBridgeTimeoutMs } = require("./constants");
const { bridgeCommand, bridgeEnv, bridgeWorkingDirectory } = require("./environment");
const { parseBridgeJsonOutput, processBridgeStreamBuffer, processBridgeStreamLine } = require("./stream");

const activeBridgeProcesses = new Set();
const processExitPollMs = 25;
const terminationGraceMs = 5000;
let bridgeShutdownStarted = false;

class BridgeCleanupPendingError extends Error {
  constructor(message, completion) {
    super(message);
    this.name = "BridgeCleanupPendingError";
    this.completion = completion;
  }
}

function runBridge(args, options = {}) {
  return runBridgeJson(args, { timeoutMs: options.timeoutMs || bridgeTimeoutMs });
}

function runBridgeJson(args, options = {}) {
  return runBridgeProcess(args, {
    timeoutMs: options.timeoutMs || bridgeTimeoutMs,
    onStdout: (state, chunk) => {
      state.stdout += chunk;
    },
    onClose: (state, finish) => {
      finish(parseBridgeJsonOutput(state.stdout, state.stderr));
    },
  });
}

function runBridgeStreaming(args, options = {}) {
  return runBridgeProcess(args, {
    timeoutMs: options.timeoutMs || flashBridgeTimeoutMs,
    onStdout: (state, chunk) => {
      state.stdout += chunk;
      state.stdout = processBridgeStreamBuffer(state.stdout, options.webContents, (payload) => {
        state.finalPayload = payload;
      });
    },
    onClose: (state, finish) => {
      const remaining = state.stdout.trim();
      if (remaining) {
        processBridgeStreamLine(remaining, options.webContents, (payload) => {
          state.finalPayload = payload;
        });
      }
      if (state.finalPayload) {
        finish(state.finalPayload);
        return;
      }
      finish({
        ok: false,
        errors: [state.stderr.trim() || "EasyMANET bridge returned no flash result"],
        raw: state.fullStdout.trim(),
      });
    },
  });
}

function runBridgeProcess(args, handlers) {
  if (bridgeShutdownStarted) {
    return Promise.resolve({ ok: false, errors: ["EasyMANET bridge is shutting down"] });
  }
  let bridge;
  try {
    bridge = bridgeCommand(args);
  } catch (error) {
    return Promise.resolve({ ok: false, errors: [error.message] });
  }
  return runTrackedProcess(
    {
      command: bridge.command,
      args: bridge.args,
      options: {
        cwd: bridgeWorkingDirectory(),
        env: bridgeEnv(),
        stdio: ["ignore", "pipe", "pipe"],
      },
    },
    handlers,
  );
}

function runTrackedProcess(launch, handlers) {
  return new Promise((resolve) => {
    if (bridgeShutdownStarted) {
      resolve({ ok: false, errors: ["EasyMANET bridge is shutting down"] });
      return;
    }
    let child;
    try {
      child = spawn(launch.command, launch.args, {
        ...launch.options,
        detached: process.platform !== "win32",
      });
    } catch (error) {
      resolve({ ok: false, errors: [error.message] });
      return;
    }
    const state = {
      stdout: "",
      fullStdout: "",
      stderr: "",
      finalPayload: null,
    };
    let settled = false;
    let timer = null;
    let resolveClose;
    const closePromise = new Promise((closeResolve) => {
      resolveClose = closeResolve;
    });
    child.once("close", resolveClose);
    const operation = {
      child,
      closePromise,
      terminationGraceMs: handlers.terminationGraceMs || terminationGraceMs,
      terminating: null,
    };
    activeBridgeProcesses.add(operation);

    const finish = (payload) => {
      if (settled) {
        return;
      }
      settled = true;
      if (timer) {
        clearTimeout(timer);
      }
      activeBridgeProcesses.delete(operation);
      resolve(payload);
    };

    const terminate = (payload) => {
      if (settled) {
        return Promise.resolve();
      }
      if (!operation.terminating) {
        operation.terminating = terminateBridgeProcessTree(
          child,
          closePromise,
          operation.terminationGraceMs,
        )
          .then(() => finish(payload))
          .catch((error) => {
            const failurePayload = {
              ...payload,
              ok: false,
              errors: [...payload.errors, `Bridge process cleanup failed: ${error.message}`],
            };
            if (error instanceof BridgeCleanupPendingError) {
              error.completion
                .then(() => finish(failurePayload))
                .catch((completionError) => {
                  const prefix = state.stderr ? "\n" : "";
                  state.stderr += `${prefix}Bridge cleanup observation failed: ${completionError.message}`;
                });
              throw error;
            }
            finish(failurePayload);
          });
      }
      return operation.terminating;
    };
    operation.terminate = terminate;

    const terminateInBackground = (payload) => {
      terminate(payload).catch((error) => {
        const prefix = state.stderr ? "\n" : "";
        state.stderr += `${prefix}Bridge process cleanup failed: ${error.message}`;
      });
    };

    const timeoutMs = handlers.timeoutMs;
    timer = setTimeout(() => {
      terminateInBackground({
        ok: false,
        errors: [handlers.timeoutMessage || `EasyMANET bridge timed out after ${timeoutMs / 1000}s`],
      });
    }, timeoutMs);

    child.stdout.on("data", (chunk) => {
      const text = chunk.toString();
      state.fullStdout += text;
      handlers.onStdout(state, text);
    });
    child.stderr.on("data", (chunk) => {
      state.stderr += chunk.toString();
    });
    child.on("error", (error) => {
      if (!child.pid) {
        finish({ ok: false, errors: [error.message] });
        return;
      }
      terminateInBackground({ ok: false, errors: [error.message] });
    });
    child.on("close", () => {
      if (operation.terminating) {
        return;
      }
      if (process.platform !== "win32" && child.pid && processGroupExists(child.pid)) {
        terminateInBackground({
          ok: false,
          errors: ["EasyMANET bridge exited before its child processes"],
        });
        return;
      }
      try {
        handlers.onClose(state, finish);
      } catch (error) {
        finish({ ok: false, errors: [error.message] });
      }
    });
    if (handlers.onSpawn) {
      try {
        handlers.onSpawn(child);
      } catch (error) {
        terminateInBackground({ ok: false, errors: [error.message] });
      }
    }
  });
}

async function shutdownActiveBridgeProcesses() {
  bridgeShutdownStarted = true;
  while (activeBridgeProcesses.size > 0) {
    const operations = [...activeBridgeProcesses];
    await Promise.all(
      operations.map((operation) => operation.terminate({
        ok: false,
        errors: ["EasyMANET bridge stopped during application shutdown"],
      })),
    );
  }
}

function hasActiveBridgeProcesses() {
  return activeBridgeProcesses.size > 0;
}

async function terminateBridgeProcessTree(child, closePromise, graceMs) {
  const pid = child.pid;
  if (!pid) {
    await closePromise;
    return;
  }

  if (process.platform === "win32") {
    child.kill("SIGTERM");
    if (!(await waitForClose(closePromise, graceMs))) {
      child.kill("SIGKILL");
      await waitForClose(closePromise, graceMs);
    }
    return;
  }

  let terminationError = null;
  try {
    signalProcessGroup(pid, "SIGTERM");
    if (await waitForProcessGroupExit(pid, graceMs)) {
      await waitForClose(closePromise, graceMs);
      return;
    }
  } catch (error) {
    terminationError = error;
  }

  let killError = null;
  try {
    signalProcessGroup(pid, "SIGKILL");
  } catch (error) {
    killError = error;
  }
  const [, processGroupExited] = await Promise.all([
    waitForClose(closePromise, graceMs),
    waitForProcessGroupExit(pid, graceMs),
  ]);
  let cleanupError = null;
  if (terminationError && killError) {
    cleanupError = new Error(
      `SIGTERM failed: ${terminationError.message}; SIGKILL failed: ${killError.message}`,
    );
  } else {
    cleanupError = terminationError || killError;
  }
  if (!processGroupExited) {
    const detail = cleanupError ? `${cleanupError.message}; ` : "";
    throw new BridgeCleanupPendingError(
      `${detail}process group ${pid} is still active`,
      waitForProcessGroupExit(pid),
    );
  }
  if (cleanupError) {
    throw cleanupError;
  }
}

function signalProcessGroup(pid, signal) {
  try {
    process.kill(-pid, signal);
  } catch (error) {
    if (error.code !== "ESRCH") {
      throw error;
    }
  }
}

async function waitForProcessGroupExit(pid, timeoutMs = null) {
  const deadline = timeoutMs === null ? null : Date.now() + timeoutMs;
  while (processGroupExists(pid)) {
    if (deadline !== null && Date.now() >= deadline) {
      return false;
    }
    await delay(processExitPollMs);
  }
  return true;
}

function processGroupExists(pid) {
  try {
    process.kill(-pid, 0);
    return true;
  } catch (error) {
    if (error.code === "ESRCH") {
      return false;
    }
    if (error.code === "EPERM") {
      return true;
    }
    throw error;
  }
}

async function waitForClose(closePromise, timeoutMs) {
  let timer;
  const timedOut = new Promise((resolve) => {
    timer = setTimeout(() => resolve(false), timeoutMs);
  });
  const closed = closePromise.then(() => true);
  const result = await Promise.race([closed, timedOut]);
  clearTimeout(timer);
  return result;
}

function delay(milliseconds) {
  return new Promise((resolve) => setTimeout(resolve, milliseconds));
}

module.exports = {
  hasActiveBridgeProcesses,
  runBridge,
  runBridgeJson,
  runBridgeProcess,
  runBridgeStreaming,
  runTrackedProcess,
  shutdownActiveBridgeProcesses,
};
