// Browser/Electron bridge routing for the EasyMANET desktop UI.
(function () {
  const nativeApi = window.easymanet || null;

  async function getJson(url) {
    if (nativeApi && url === "/api/state") {
      return nativeApi.getState();
    }
    return fetchJson(url);
  }

  async function postJson(url, body) {
    if (nativeApi && url === "/api/validate") {
      return nativeApi.validate(body);
    }
    if (nativeApi && nativeApi.discoverMesh && url === "/api/mesh/discover") {
      return nativeApi.discoverMesh(body);
    }
    if (nativeApi && nativeApi.runDiagnostics && url === "/api/diagnostics/run") {
      return nativeApi.runDiagnostics(body);
    }
    if (nativeApi && nativeApi.exportDiagnosticsBundle && url === "/api/diagnostics/bundle") {
      return nativeApi.exportDiagnosticsBundle(body);
    }
    if (nativeApi && nativeApi.importBootReport && url === "/api/diagnostics/import-boot-report") {
      return nativeApi.importBootReport(body);
    }
    return fetchJson(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
  }

  async function fetchJson(url, options) {
    let response;
    try {
      response = await fetch(url, options);
    } catch (error) {
      throw new Error(`Request failed for ${url}: ${error.message}`);
    }

    const text = await response.text();
    let payload = {};
    if (text) {
      try {
        payload = JSON.parse(text);
      } catch (error) {
        throw new Error(`Invalid JSON from ${url}: ${error.message}`);
      }
    }

    if (!response.ok) {
      const detail = errorDetail(payload) || text;
      const suffix = detail ? ` - ${detail}` : "";
      throw new Error(`Request failed for ${url}: ${response.status} ${response.statusText}${suffix}`);
    }
    return payload;
  }

  function errorDetail(payload) {
    if (!payload || typeof payload !== "object") {
      return "";
    }
    if (payload.error) {
      return payload.error;
    }
    if (Array.isArray(payload.errors)) {
      return payload.errors.join(", ");
    }
    return "";
  }

  function errorMessage(error) {
    return error && error.message ? error.message : String(error);
  }

  async function getState() {
    return getJson("/api/state");
  }

  async function getDisks(includeAll) {
    if (nativeApi) {
      return nativeApi.getDisks(includeAll);
    }
    const suffix = includeAll ? "?all=1" : "";
    return getJson(`/api/disks${suffix}`);
  }

  window.EMApi = {
    nativeApi,
    getJson,
    postJson,
    fetchJson,
    errorDetail,
    errorMessage,
    getState,
    getDisks,
  };
})();
