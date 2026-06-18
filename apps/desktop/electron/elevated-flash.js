const { spawn } = require("node:child_process");
const fs = require("node:fs");
const path = require("node:path");
const { flashBridgeTimeoutMs, repoRoot } = require("./constants");
const { elevatedBridgeCommand, elevatedBridgeEnv, elevatedTempRoot, sudoBridgeCommand } = require("./environment");
const { runBridge, runBridgeStreaming } = require("./bridge-process");
const { parseElevatedBridgeOutput, processBridgeStreamBuffer, processBridgeStreamLine, sendBridgeFlashEvent } = require("./stream");
const { flashArgs } = require("./validation");

async function runFlashWithAdministratorPrivileges(validated, options = {}) {
  let plan = await runBridge(["flash-plan", ...flashArgs(validated)], {
    timeoutMs: options.timeoutMs || flashBridgeTimeoutMs,
  });
  if (!plan.ok) {
    return plan;
  }
  const ensured = await ensureCachedImageForElevatedFlash(validated, plan, options);
  if (ensured.ok === false) {
    return ensured;
  }
  plan = ensured;
  sendBridgeFlashEvent(options.webContents, {
    type: "event",
    event_type: "auth_required",
    level: "info",
    message: "Administrator authentication is required to write the selected disk.",
  });
  let stage = null;
  try {
    stage = stageElevatedFlashInputs(validated, plan);
    const stagedPayload = {...validated, config: stage.configPath};
    const stagedImage = stage.imagePath ? {...plan.image, cached_path: stage.imagePath} : plan.image || {};
    const args = ["flash", ...flashArgs(stagedPayload), "--yes", ...baseImageArgs(stagedImage)];
    return await runBridgeWithAdministratorPrivileges(args, {...options, stage});
  } catch (error) {
    cleanupElevatedStage(stage);
    return {ok: false, errors: [error.message]};
  }
}

async function ensureCachedImageForElevatedFlash(validated, plan, options = {}) {
  const image = plan.image || {};
  const imagePath = String(image.cached_path || image.path || "");
  if (imagePath && !imagePath.startsWith("<")) {
    return plan;
  }
  if (!image.url || !image.sha256) {
    return plan;
  }

  const result = await runBridgeStreaming(["ensure-image", "--config", validated.config, "--node", validated.node], {
    timeoutMs: options.timeoutMs || flashBridgeTimeoutMs,
    webContents: options.webContents,
  });
  if (!result.ok) {
    return result;
  }
  return {
    ...plan,
    image: {
      ...image,
      ...(result.image || {}),
    },
  };
}

function runBridgeWithAdministratorPrivileges(args, options = {}) {
  return new Promise((resolve) => {
    let bridge;
    try {
      bridge = elevatedBridgeCommand(args, options.stage);
    } catch (error) {
      cleanupElevatedStage(options.stage);
      resolve({ ok: false, errors: [error.message] });
      return;
    }

    const timeoutMs = options.timeoutMs || flashBridgeTimeoutMs;
    const effectiveTimeoutMs = timeoutMs + 60000;
    const sudo = sudoBridgeCommand(bridge);
    const child = spawn(sudo.command, sudo.args, {
      cwd: bridge.cwd || elevatedTempRoot(),
      env: elevatedBridgeEnv(bridge.env || {}),
      stdio: ["pipe", "pipe", "pipe"],
      detached: process.platform !== "win32",
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
      cleanupElevatedStage(options.stage);
      resolve(payload);
    };

    const timer = setTimeout(() => {
      terminateElevatedBridge(child);
      finish({ ok: false, errors: [`Administrator flash timed out after ${effectiveTimeoutMs / 1000}s`] });
    }, effectiveTimeoutMs);

    child.stdout.on("data", (chunk) => {
      const text = chunk.toString();
      state.fullStdout += text;
      state.stdout += text;
      state.stdout = processBridgeStreamBuffer(state.stdout, options.webContents, (payload) => {
        state.finalPayload = payload;
      });
    });
    child.stderr.on("data", (chunk) => {
      state.stderr += chunk.toString();
    });
    child.on("error", (error) => {
      finish({ ok: false, errors: [error.message] });
    });
    child.on("close", () => {
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
      finish(parseElevatedBridgeOutput(state.fullStdout, state.stderr, options.webContents));
    });
    child.stdin.write(`${options.adminPassword || ""}\n`);
    child.stdin.end();
  });
}

function terminateElevatedBridge(child) {
  if (process.platform !== "win32" && child.pid) {
    try {
      process.kill(-child.pid, "SIGTERM");
      const killTimer = setTimeout(() => {
        try {
          process.kill(-child.pid, "SIGKILL");
        } catch (_error) {
          // Process already exited.
        }
      }, 5000);
      if (typeof killTimer.unref === "function") {
        killTimer.unref();
      }
      return;
    } catch (_error) {
      // Fall through to killing the wrapper process.
    }
  }
  child.kill("SIGTERM");
}

function stageElevatedFlashInputs(validated, plan) {
  const root = fs.mkdtempSync(path.join(elevatedTempRoot(), "easymanet-flash-"));
  const inputDir = path.join(root, "input");
  const sourceDir = path.join(root, "src");
  const workspaceDir = path.join(root, "workspace");
  fs.mkdirSync(inputDir, {recursive: true});
  fs.mkdirSync(sourceDir, {recursive: true});
  fs.mkdirSync(workspaceDir, {recursive: true});

  const configPath = path.join(inputDir, path.basename(validated.config) || "fleet.yml");
  fs.copyFileSync(validated.config, configPath);
  fs.chmodSync(configPath, 0o600);

  const sourceImagePath = String((plan.image || {}).cached_path || (plan.image || {}).path || "");
  let imagePath = "";
  if (sourceImagePath && !sourceImagePath.startsWith("<")) {
    imagePath = path.join(inputDir, path.basename(sourceImagePath));
    fs.copyFileSync(sourceImagePath, imagePath);
    fs.chmodSync(imagePath, 0o644);
  }

  copyPythonPackage(path.join(repoRoot, "packages", "core", "src", "easymanet"), path.join(sourceDir, "easymanet"));
  copyPythonPackage(path.join(repoRoot, "apps", "cli", "src", "easymanet_cli"), path.join(sourceDir, "easymanet_cli"));
  copyPythonPackage(
    path.join(repoRoot, "apps", "desktop", "src", "easymanet_desktop"),
    path.join(sourceDir, "easymanet_desktop")
  );

  return {
    root,
    configPath,
    imagePath,
    sourceRoots: [sourceDir],
    workspaceDir,
  };
}

function copyPythonPackage(from, to) {
  if (!fs.existsSync(from)) {
    return;
  }
  fs.cpSync(from, to, {
    recursive: true,
    filter: (src) => !src.includes(`${path.sep}__pycache__${path.sep}`),
  });
}

function cleanupElevatedStage(stage) {
  if (!stage || !stage.root) {
    return;
  }
  const root = path.resolve(stage.root);
  if (!root.startsWith(path.resolve(elevatedTempRoot()) + path.sep)) {
    return;
  }
  try {
    fs.rmSync(root, {recursive: true, force: true});
  } catch (_error) {
    // Root-owned files should not block the desktop result.
  }
}

function baseImageArgs(image) {
  const imagePath = String(image.cached_path || image.path || "");
  if (!imagePath || imagePath.startsWith("<")) {
    return [];
  }
  const args = ["--base-image", imagePath];
  const sha256 = String(image.sha256 || "");
  if (sha256) {
    args.push("--image-sha256", sha256);
  }
  return args;
}

module.exports = {
  baseImageArgs,
  cleanupElevatedStage,
  ensureCachedImageForElevatedFlash,
  runBridgeWithAdministratorPrivileges,
  runFlashWithAdministratorPrivileges,
  stageElevatedFlashInputs,
};
