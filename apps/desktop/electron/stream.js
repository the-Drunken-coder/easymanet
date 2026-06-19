function parseBridgeJsonOutput(stdout, stderr) {
  const text = stdout.trim();
  if (!text) {
    return { ok: false, errors: [stderr.trim() || "EasyMANET bridge returned no output"] };
  }
  try {
    return JSON.parse(text);
  } catch (error) {
    return { ok: false, errors: [error.message], raw: text, stderr: stderr.trim() };
  }
}

function parseElevatedBridgeOutput(stdout, stderr, webContents) {
  const text = stdout.trim();
  const errorText = stderr.trim();
  if (!text) {
    if (errorText.includes("Sorry, try again") || errorText.includes("incorrect password")) {
      return { ok: false, errors: ["Administrator authentication failed"] };
    }
    if (errorText.includes("a password is required")) {
      return { ok: false, errors: ["Mac administrator password is required for flashing"] };
    }
    return { ok: false, errors: [errorText || "Administrator flash returned no output"] };
  }

  let finalPayload = null;
  const outputLines = [];
  for (const line of text.split(/\r?\n/)) {
    const trimmed = line.trim();
    if (!trimmed) {
      continue;
    }
    try {
      const payload = JSON.parse(trimmed);
      if (payload.type === "result") {
        finalPayload = payload;
      } else if (payload.type === "event") {
        sendBridgeFlashEvent(webContents, payload);
        outputLines.push(bridgeEventOutputLine(payload));
      } else if (Object.prototype.hasOwnProperty.call(payload, "ok")) {
        finalPayload = payload;
      }
    } catch (_error) {
      sendBridgeFlashEvent(webContents, {
        type: "event",
        event_type: "bridge_output",
        level: "info",
        message: trimmed,
      });
      outputLines.push(trimmed);
    }
  }
  if (finalPayload) {
    if (outputLines.length && !finalPayload.output) {
      finalPayload.output = outputLines.join("\n");
    }
    return finalPayload;
  }
  return parseBridgeJsonOutput(text, errorText);
}

function bridgeEventOutputLine(payload) {
  const message = String(payload.message || payload.event_type || "").trim();
  const prefix = payload.level === "warning" ? "warning: " : payload.level === "error" ? "error: " : "";
  return `${prefix}${message}`.trim();
}

function processBridgeStreamBuffer(buffer, webContents, setFinalPayload) {
  const lines = buffer.split(/\r?\n/);
  const tail = lines.pop() || "";
  for (const line of lines) {
    const text = line.trim();
    if (!text) {
      continue;
    }
    processBridgeStreamLine(text, webContents, setFinalPayload);
  }
  return tail;
}

function processBridgeStreamLine(text, webContents, setFinalPayload) {
  try {
    const payload = JSON.parse(text);
    if (payload.type === "result") {
      setFinalPayload(payload);
    } else if (payload.type === "event") {
      sendBridgeFlashEvent(webContents, payload);
    }
  } catch (_error) {
    sendBridgeFlashEvent(webContents, {
      type: "event",
      event_type: "bridge_output",
      level: "info",
      message: text,
    });
  }
}

function sendBridgeFlashEvent(webContents, payload) {
  if (!webContents || (typeof webContents.isDestroyed === "function" && webContents.isDestroyed())) {
    return;
  }
  try {
    webContents.send("easymanet:flash-event", payload);
  } catch (_error) {
    // The renderer may close between the isDestroyed check and the send call.
  }
}

module.exports = {
  bridgeEventOutputLine,
  parseBridgeJsonOutput,
  parseElevatedBridgeOutput,
  processBridgeStreamBuffer,
  processBridgeStreamLine,
  sendBridgeFlashEvent,
};
