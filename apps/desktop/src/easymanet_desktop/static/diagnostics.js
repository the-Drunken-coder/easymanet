// Diagnostics tab controller for the EasyMANET desktop UI.
(function () {
  const { byId: $, showCopied } = window.EMDom;
  const { nativeApi, postJson, errorDetail, errorMessage } = window.EMApi;

  const diagnosticsForm = $("diagnostics-form");
  const diagnosticsStatusChip = $("diagnostics-status-chip");
  const diagnosticsConfigSource = $("diagnostics-config-source");
  const diagnosticsRun = $("diagnostics-run");
  const diagnosticsExport = $("diagnostics-export");
  const diagnosticsImportSource = $("diagnostics-import-source");
  const diagnosticsImport = $("diagnostics-import");
  const diagnosticsResult = $("diagnostics-result");
  const diagnosticsOutput = $("diagnostics-output");
  const diagnosticsCopy = $("diagnostics-copy");

  let currentConfig = "";

  diagnosticsForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    await runDiagnostics();
  });
  diagnosticsExport.addEventListener("click", async () => {
    await exportDiagnosticsBundle();
  });
  diagnosticsImport.addEventListener("click", async () => {
    await importOfflineBootReport();
  });
  diagnosticsCopy.addEventListener("click", async () => {
    await copyDiagnosticsSummary();
  });

  function updateFleetSource(config) {
    currentConfig = String(config || "").trim();
    diagnosticsConfigSource.textContent = currentConfig || "No fleet selected";
    diagnosticsConfigSource.title = currentConfig || "";
  }

  async function runDiagnostics() {
    setDiagnosticsBusy(true, "running");
    try {
      const response = await postJson("/api/diagnostics/run", {
        config: currentConfig,
      });
      renderDiagnostics(response);
    } catch (error) {
      renderDiagnosticsError(error);
    } finally {
      setDiagnosticsBusy(false);
    }
  }

  async function exportDiagnosticsBundle() {
    setDiagnosticsBusy(true, "exporting");
    try {
      const response = await postJson("/api/diagnostics/bundle", {
        config: currentConfig,
      });
      renderDiagnostics(response);
      if (response.bundle_path) {
        renderDiagnosticsResult({ ok: true, message: `Support bundle: ${response.bundle_path}` });
      }
    } catch (error) {
      renderDiagnosticsError(error);
    } finally {
      setDiagnosticsBusy(false);
    }
  }

  async function importOfflineBootReport() {
    const source = diagnosticsImportSource.value.trim();
    if (!source) {
      renderDiagnosticsResult({ ok: false, message: "Boot report source path is required." });
      return;
    }
    setDiagnosticsBusy(true, "importing");
    try {
      const response = await postJson("/api/diagnostics/import-boot-report", { source });
      const count = (response.imported || []).length;
      renderDiagnosticsResult({
        ok: Boolean(response.ok),
        message: response.ok ? `Imported ${count} boot report folder(s).` : errorDetail(response),
      });
    } catch (error) {
      renderDiagnosticsError(error);
    } finally {
      setDiagnosticsBusy(false);
    }
  }

  async function copyDiagnosticsSummary() {
    const text = diagnosticsOutput.textContent.trim();
    if (!nativeApi || !text) {
      return;
    }
    const result = await nativeApi.copyText(text);
    if (result.ok) {
      showCopied(diagnosticsCopy, "Copy Summary");
    } else {
      renderDiagnosticsResult({ ok: false, message: errorDetail(result) || "Could not copy support summary." });
    }
  }

  function renderDiagnostics(payload) {
    const summary = payload.summary || "";
    diagnosticsOutput.textContent = summary || JSON.stringify(payload, null, 2);
    setDiagnosticsStatus(payload.ok ? "ok" : "warn", payload.support_code || (payload.ok ? "ready" : "issues"));
    renderDiagnosticsResult({
      ok: Boolean(payload.ok),
      message: payload.bundle_path ? `Support bundle: ${payload.bundle_path}` : payload.support_code || "Diagnostics complete",
    });
  }

  function renderDiagnosticsError(error) {
    const message = errorMessage(error);
    setDiagnosticsStatus("bad", "error");
    renderDiagnosticsResult({ ok: false, message });
  }

  function renderDiagnosticsResult(payload) {
    diagnosticsResult.hidden = false;
    diagnosticsResult.className = `validation ${payload.ok ? "ok" : "bad"}`;
    diagnosticsResult.textContent = payload.message || "";
  }

  function setDiagnosticsBusy(busy, label = "running") {
    diagnosticsRun.disabled = busy;
    diagnosticsExport.disabled = busy;
    diagnosticsImport.disabled = busy;
    diagnosticsCopy.disabled = busy;
    setDiagnosticsStatus(busy ? "warn" : "subtle", busy ? label : "idle");
  }

  function setDiagnosticsStatus(tone, label) {
    diagnosticsStatusChip.textContent = label;
    diagnosticsStatusChip.className = `chip ${tone}`;
  }

  window.EMDiagnostics = {
    updateFleetSource,
  };
})();
