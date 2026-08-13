// Markup builders and formatters for the EasyMANET operator console.
// Loaded before app.js; exposes a single EMRender namespace.
(function () {
  "use strict";

  const ALLOWED_TONES = new Set(["ok", "warn", "bad", "subtle"]);

  function escapeHtml(value) {
    return String(value)
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#039;");
  }

  function formatBytes(value) {
    const bytes = Number(value);
    if (!Number.isFinite(bytes) || bytes < 0) {
      return "";
    }
    const units = ["B", "KB", "MB", "GB", "TB"];
    let size = bytes;
    let unit = 0;
    while (size >= 1024 && unit < units.length - 1) {
      size /= 1024;
      unit += 1;
    }
    const rendered = size >= 10 || unit === 0 ? Math.round(size).toString() : size.toFixed(1);
    return `${rendered} ${units[unit]}`;
  }

  function statusText(tone, text) {
    return `<span class="status-text" data-tone="${safeTone(tone)}">${escapeHtml(text)}</span>`;
  }

  function safeTone(tone) {
    return ALLOWED_TONES.has(tone) ? tone : "subtle";
  }

  function imageRow(target, image) {
    const cached = Boolean(image.cached_path) && image.cache_present !== false;
    const updateAvailable = Boolean(image.update_available);
    const installing = Boolean(image.installing);
    const anyInstallRunning = Boolean(image.anyInstallRunning);
    const trustStatus = String(image.trust_status || image.trust_status === "" ? image.trust_status : image.trustStatus || "");
    const imageStatus = String(image.image_status ?? image.imageStatus ?? "");
    const source = String(image.source ?? image.imageSource ?? "");
    const configuredSha = String(image.sha256 || "");
    const cachedSha = String(image.cached_sha256 || "");
    const cachedSize = formatBytes(image.cached_size_bytes);
    const trustLabel = trustStatus === "verified"
      ? "verified official"
      : trustStatus === "untrusted"
        ? "untrusted official"
        : source === "custom" || trustStatus === "checksum-only"
          ? "checksum-only custom"
          : cached ? "checksum-only" : "needs download";
    const evidence = [];
    if (updateAvailable) {
      evidence.push(`new image available: ${escapeHtml(image.latest_version || "latest")}`);
    }
    if (imageStatus === "superseded" || imageStatus === "unsafe") {
      evidence.push(`warning: ${escapeHtml(imageStatus)}`);
    }
    for (const warning of image.warnings || []) {
      evidence.push(escapeHtml(warning));
    }
    if (cached && cachedSize) {
      evidence.push(escapeHtml(cachedSize));
    }
    if (!cached) {
      evidence.push("Preview or flash will fetch this image.");
    }
    if (image.url) {
      evidence.push(`<span class="mono">${escapeHtml(image.url)}</span>`);
    }
    if (configuredSha) {
      evidence.push(`<span class="mono">configured sha ${escapeHtml(configuredSha.slice(0, 16))}&hellip;</span>`);
    }
    if (cachedSha && cachedSha !== configuredSha) {
      evidence.push(`<span class="mono">cached sha ${escapeHtml(cachedSha.slice(0, 16))}&hellip;</span>`);
    }
    const updateControl = updateAvailable
      ? `<button class="btn ghost small" type="button" data-image-install-target="${escapeHtml(target)}"${installing || anyInstallRunning ? " disabled" : ""}>${installing ? "Installing..." : "Install Update"}</button>`
      : "";
    const action = [...evidence, updateControl].filter(Boolean).join("<br>");
    return `
      <tr class="image-row">
        <th scope="row" class="mono">${escapeHtml(target)}</th>
        <td>${escapeHtml(image.version || "unversioned")}</td>
        <td>${statusText(updateAvailable ? "warn" : cached ? "ok" : "warn", updateAvailable ? "update available" : cached ? "cached" : "will download")}</td>
        <td>${statusText(trustStatus === "verified" ? "ok" : trustStatus === "untrusted" ? "bad" : cached ? "warn" : "subtle", trustLabel)}</td>
        <td class="evidence-cell">${action}</td>
      </tr>
    `;
  }

  function diskRow(disk, selectedDevice) {
    const selected = disk.device === selectedDevice;
    const warnings = (disk.warnings || []).map(escapeHtml).join("; ");
    const mounted = (disk.mounted || []).join(", ");
    const media = disk.virtual
      ? statusText("warn", "virtual")
      : statusText(disk.removable ? "ok" : "warn", disk.removable ? "removable" : "fixed");
    return `
      <tr class="disk-row${selected ? " selected" : ""}">
        <th scope="row"><button type="button" class="disk-select mono" data-device="${escapeHtml(disk.device)}" aria-pressed="${selected}">${escapeHtml(disk.device)}</button></th>
        <td>${escapeHtml(disk.model || "Unknown model")}${warnings ? `<br><span class="disk-warning">${warnings}</span>` : ""}</td>
        <td>${escapeHtml(disk.size_human || "size unknown")}</td>
        <td>${media}</td>
        <td class="mono">${escapeHtml(mounted || "not mounted")}</td>
      </tr>
    `;
  }

  function statusRow(tone, text) {
    return `<div class="v-row ${tone}"><span class="v-dot" aria-hidden="true"></span><span class="v-text">${escapeHtml(text)}</span></div>`;
  }

  function validationMarkup(payload) {
    const rows = [];
    if (payload.ok) {
      rows.push(statusRow("ok", "Fleet configuration is valid"));
    }
    for (const error of payload.errors || []) {
      rows.push(statusRow("bad", error));
    }
    for (const warning of payload.warnings || []) {
      rows.push(statusRow("warn", warning));
    }
    const nodes = payload.nodes || [];
    if (nodes.length) {
      const label = nodes.length === 1 ? "1 node" : `${nodes.length} nodes`;
      rows.push(statusRow("subtle", `${label}: ${nodes.join(", ")}`));
    }
    return rows.join("") || statusRow("subtle", "No result");
  }

  function planSshValue(plan) {
    if (typeof plan.ssh_enabled === "boolean") {
      return plan.ssh_enabled ? "enabled" : "disabled";
    }
    return plan.ssh;
  }

  function planWanApiValue(plan) {
    if (typeof plan.api_wan_enabled === "boolean") {
      return plan.api_wan_enabled ? "enabled" : "disabled";
    }
    return plan.api_wan;
  }

  function planDetailsElement(label, text) {
    if (!text) {
      return null;
    }
    const details = document.createElement("details");
    details.className = "plan-details";

    const summary = document.createElement("summary");
    summary.textContent = label;

    const pre = document.createElement("pre");
    pre.textContent = text;

    details.append(summary, pre);
    return details;
  }

  function planTableElements(payload) {
    const plan = payload.plan || {};
    const image = payload.image || {};
    const imagePath = image.cached_path || plan.base_image || image.url || "";
    const table = document.createElement("table");
    table.className = "state-table";
    table.setAttribute("aria-label", "Flash plan");
    const body = document.createElement("tbody");
    for (const [label, value] of [
      ["Node", plan.node],
      ["Hostname", plan.hostname],
      ["Role", plan.role],
      ["Target", plan.target],
      ["Device", plan.device],
      ["Image", imagePath],
      ["Version", image.version],
      ["SSH", planSshValue(plan)],
      ["WAN API", planWanApiValue(plan)],
      ["Boot payload", plan.boot_payload],
    ]) {
      if (value === undefined || value === null || value === "") {
        continue;
      }
      const row = document.createElement("tr");
      const key = document.createElement("th");
      key.setAttribute("scope", "row");
      key.textContent = label;
      const planValue = document.createElement("td");
      planValue.className = "mono";
      planValue.textContent = String(value);
      row.append(key, planValue);
      body.appendChild(row);
    }
    table.appendChild(body);

    return [
      table,
      planDetailsElement("Provision payload", payload.provision_display),
      planDetailsElement("Boot files", payload.dry_run_info),
    ].filter(Boolean);
  }

  function meshNodeRow(node) {
    const title = node.name || node.hostname || node.node || node.host || node.ip || node.address || "unknown";
    const status = node.status || "seen";
    const details = [
      node.summary,
      node.target,
      node.mesh_mac,
      node.bat0_mac,
      node.expected_ip,
      node.expected_hostname,
      node.source,
      node.error || node.stderr,
    ].filter(Boolean).map(escapeHtml).join("; ");
    return `
      <tr>
        <th scope="row" class="mono">${escapeHtml(title)}</th>
        <td class="mono">${escapeHtml(node.ip || node.node_ip || node.address || node.host || "")}</td>
        <td>${escapeHtml(node.role || "")}</td>
        <td>${statusText(status === "online" || status === "connected" ? "ok" : "warn", status)}</td>
        <td class="mono">${details}</td>
      </tr>
    `;
  }

  function meshLinkRow(link) {
    const source = link.source || link.source_node || "unknown";
    const target = link.target || link.target_node || link.target_mac || "unresolved";
    const status = link.status || (link.target ? "resolved" : "unresolved");
    const meta = [link.iface, link.last_seen, link.throughput].filter(Boolean).join(" / ");
    return `
      <tr>
        <th scope="row" class="mono">${escapeHtml(source)}</th>
        <td class="mono">${escapeHtml(target)}</td>
        <td>${statusText(status === "resolved" ? "ok" : "warn", status)}</td>
        <td class="mono">${escapeHtml(meta)}</td>
      </tr>
    `;
  }

  function meshTopologyView(payload) {
    const nodes = payload.nodes || payload.radios || [];
    const links = payload.links || [];
    const nodeMarkup = nodes.map(meshNodeRow).join("");
    const emptyLinksMeta = payload.degraded
      ? "Reachable node APIs did not report active BATMAN neighbors."
      : "The gateway API did not report active BATMAN neighbors.";
    const linkMarkup = links.length
      ? `<div class="table-wrap"><table class="data-table" aria-label="Discovered mesh links"><thead><tr><th scope="col">Source</th><th scope="col">Target</th><th scope="col">State</th><th scope="col">Evidence</th></tr></thead><tbody>${links.map(meshLinkRow).join("")}</tbody></table></div>`
      : `<div class="empty-state slim"><p class="empty-title">No links reported</p><p class="empty-meta">${emptyLinksMeta}</p></div>`;
    return `
      <div class="topology-section">
        <div class="table-wrap"><table class="data-table" aria-label="Discovered mesh nodes"><thead><tr><th scope="col">Node</th><th scope="col">Address</th><th scope="col">Role</th><th scope="col">State</th><th scope="col">Evidence</th></tr></thead><tbody>${nodeMarkup}</tbody></table></div>
      </div>
      <div class="topology-section">
        <div class="section-title">Links</div>
        ${linkMarkup}
      </div>
    `;
  }

  function meshDiscoveryMarkup(payload) {
    const rows = [];
    const checked = Number(payload.candidates_checked) || 0;
    const nodes = payload.nodes || payload.radios || [];
    const links = payload.links || [];
    if (payload.degraded) {
      rows.push(statusRow("warn", `${nodes.length} partial nodes found; gateway unreachable`));
      rows.push(statusRow("subtle", `${links.length} links reported from reachable node APIs`));
      rows.push(statusRow("subtle", `${checked} candidates checked`));
    } else if (payload.ok) {
      rows.push(statusRow(nodes.length ? "ok" : "subtle", `${nodes.length} nodes found`));
      if (nodes.length) {
        rows.push(statusRow("subtle", `${links.length} links reported`));
      }
      rows.push(statusRow("subtle", `${checked} candidates checked`));
    }
    for (const warning of payload.warnings || []) {
      rows.push(statusRow("warn", warning));
    }
    for (const error of payload.errors || []) {
      rows.push(statusRow("bad", error));
    }
    return rows.join("") || statusRow("subtle", "No discovery result");
  }

  window.EMRender = {
    escapeHtml,
    formatBytes,
    safeTone,
    imageRow,
    diskRow,
    validationMarkup,
    planTableElements,
    meshTopologyView,
    meshDiscoveryMarkup,
  };
})();
