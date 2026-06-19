const { spawn } = require("node:child_process");
const { bridgeTimeoutMs, flashBridgeTimeoutMs } = require("./constants");
const { bridgeCommand, bridgeEnv, bridgeWorkingDirectory } = require("./environment");
const { parseBridgeJsonOutput, processBridgeStreamBuffer, processBridgeStreamLine } = require("./stream");

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
  return new Promise((resolve) => {
    let bridge;
    try {
      bridge = bridgeCommand(args);
    } catch (error) {
      resolve({ ok: false, errors: [error.message] });
      return;
    }
    const child = spawn(bridge.command, bridge.args, {
      cwd: bridgeWorkingDirectory(),
      env: bridgeEnv(),
      stdio: ["ignore", "pipe", "pipe"],
    });
    const state = {
      stdout: "",
      fullStdout: "",
      stderr: "",
      finalPayload: null,
    };
    let settled = false;

    const finish = (payload) => {
      if (settled) {
        return;
      }
      settled = true;
      clearTimeout(timer);
      resolve(payload);
    };

    const timeoutMs = handlers.timeoutMs;
    const timer = setTimeout(() => {
      child.kill();
      finish({ ok: false, errors: [`EasyMANET bridge timed out after ${timeoutMs / 1000}s`] });
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
      finish({ ok: false, errors: [error.message] });
    });
    child.on("close", () => {
      handlers.onClose(state, finish);
    });
  });
}

module.exports = {
  runBridge,
  runBridgeJson,
  runBridgeProcess,
  runBridgeStreaming,
};
