const fs = require("node:fs");
const path = require("node:path");
const { flashBridgeTimeoutMs, repoRoot } = require("./constants");
const { elevatedBridgeCommand, elevatedBridgeEnv, elevatedTempRoot, sudoBridgeCommand } = require("./environment");
const { runBridgeStreaming, runTrackedProcess } = require("./bridge-process");
const { parseElevatedBridgeOutput, processBridgeStreamBuffer, processBridgeStreamLine, sendBridgeFlashEvent } = require("./stream");
const { flashArgs } = require("./validation");

async function runFlashWithAdministratorPrivileges(validated, options = {}) {
  const prepared = await runBridgeStreaming(["prepare-flash", ...flashArgs(validated)], {
    timeoutMs: options.timeoutMs || flashBridgeTimeoutMs,
    webContents: options.webContents,
  });
  if (!prepared.ok) {
    return prepared;
  }
  sendBridgeFlashEvent(options.webContents, {
    type: "event",
    event_type: "auth_required",
    level: "info",
    message: "Administrator authentication is required to write the selected disk.",
  });
  let stage = null;
  try {
    stage = stageElevatedFlashInputs(validated, prepared);
    const stagedPayload = {...validated, config: stage.configPath};
    const stagedImage = stage.imagePath ? {...prepared.image, cached_path: stage.imagePath} : prepared.image || {};
    const args = ["flash", ...flashArgs(stagedPayload), "--yes", ...baseImageArgs(stagedImage)];
    return await runBridgeWithAdministratorPrivileges(args, {...options, stage});
  } catch (error) {
    cleanupElevatedStage(stage);
    return {ok: false, errors: [error.message]};
  }
}

function runBridgeWithAdministratorPrivileges(args, options = {}) {
  let bridge;
  let sudo;
  try {
    bridge = elevatedBridgeCommand(args, options.stage);
    sudo = sudoBridgeCommand(bridge);
  } catch (error) {
    cleanupElevatedStage(options.stage);
    return Promise.resolve({ ok: false, errors: [error.message] });
  }

  const timeoutMs = options.timeoutMs || flashBridgeTimeoutMs;
  const authenticationGraceMs = options.authenticationGraceMs ?? 60000;
  const effectiveTimeoutMs = timeoutMs + authenticationGraceMs;
  const result = runTrackedProcess(
    {
      command: sudo.command,
      args: sudo.args,
      options: {
        cwd: bridge.cwd || elevatedTempRoot(),
        env: elevatedBridgeEnv(bridge.env || {}),
        stdio: ["pipe", "pipe", "pipe"],
      },
    },
    {
      timeoutMs: effectiveTimeoutMs,
      timeoutMessage: `Administrator flash timed out after ${effectiveTimeoutMs / 1000}s`,
      terminationGraceMs: options.terminationGraceMs,
      onSpawn: (child) => {
        child.stdin.on("error", () => {
          // Process close reports authentication or launch failures.
        });
        child.stdin.end(`${options.adminPassword || ""}\n`);
      },
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
        finish(parseElevatedBridgeOutput(state.fullStdout, state.stderr, options.webContents));
      },
    },
  );
  return result.finally(() => cleanupElevatedStage(options.stage));
}

function stageElevatedFlashInputs(validated, plan) {
  const root = fs.mkdtempSync(path.join(elevatedTempRoot(), "easymanet-flash-"));
  try {
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
  } catch (error) {
    cleanupElevatedStage({root});
    throw error;
  }
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
  runBridgeWithAdministratorPrivileges,
  runFlashWithAdministratorPrivileges,
  stageElevatedFlashInputs,
};
