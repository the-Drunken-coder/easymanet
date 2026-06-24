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

  function chip(tone, text) {
    return `<span class="chip ${safeTone(tone)}">${escapeHtml(text)}</span>`;
  }

  function safeTone(tone) {
    return ALLOWED_TONES.has(tone) ? tone : "subtle";
  }

  function imageItem(target, image) {
    const cached = Boolean(image.cached_path);
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
    const lines = [
      `<div class="item-top"><span class="item-name mono">${escapeHtml(target)}</span>${chip(updateAvailable ? "warn" : cached ? "ok" : "warn", updateAvailable ? "update available" : cached ? "cached" : "will download")}</div>`,
      `<div class="meta-line">${escapeHtml(image.version || "unversioned")}</div>`,
      `<div class="meta-line">${chip(trustStatus === "verified" ? "ok" : trustStatus === "untrusted" ? "bad" : cached ? "warn" : "subtle", trustLabel)}</div>`,
    ];
    if (updateAvailable) {
      lines.push(`
        <div class="image-update-row">
          <span class="image-action">new image available: ${escapeHtml(image.latest_version || "latest")}</span>
          <button class="btn ghost small" type="button" data-image-install-target="${escapeHtml(target)}"${installing || anyInstallRunning ? " disabled" : ""}>${installing ? "Installing..." : "Install Update"}</button>
        </div>
      `);
    }
    if (imageStatus === "superseded" || imageStatus === "unsafe") {
      lines.push(`<div class="meta-line image-action">warning: ${escapeHtml(imageStatus)}</div>`);
    }
    for (const warning of image.warnings || []) {
      lines.push(`<div class="meta-line image-action">${escapeHtml(warning)}</div>`);
    }
    if (cached && cachedSize) {
      lines.push(`<div class="meta-line">${escapeHtml(cachedSize)}</div>`);
    }
    if (!cached) {
      lines.push(`<div class="meta-line image-action">Preview or flash will fetch this image.</div>`);
    }
    if (image.url) {
      lines.push(`<div class="meta-line mono trunc" title="${escapeHtml(image.url)}">${escapeHtml(image.url)}</div>`);
    }
    if (configuredSha) {
      lines.push(`<div class="meta-line mono trunc" title="${escapeHtml(configuredSha)}">configured sha ${escapeHtml(configuredSha.slice(0, 16))}&hellip;</div>`);
    }
    if (cachedSha && cachedSha !== configuredSha) {
      lines.push(`<div class="meta-line mono trunc" title="${escapeHtml(cachedSha)}">cached sha ${escapeHtml(cachedSha.slice(0, 16))}&hellip;</div>`);
    }
    return `<div class="image-item">${lines.join("")}</div>`;
  }

  function diskCard(disk, selectedDevice) {
    const selected = disk.device === selectedDevice;
    const warnings = (disk.warnings || [])
      .map((item) => `<span class="disk-warning">${escapeHtml(item)}</span>`)
      .join("");
    const mounted = (disk.mounted || []).join(", ");
    const typeChip = disk.virtual
      ? chip("warn", "virtual")
      : chip(disk.removable ? "ok" : "warn", disk.removable ? "removable" : "fixed");
    return `
      <button type="button" class="disk-card${selected ? " selected" : ""}" data-device="${escapeHtml(disk.device)}" aria-pressed="${selected}">
        <span class="disk-top">
          <span class="disk-device mono">${escapeHtml(disk.device)}</span>
          <span class="disk-check" aria-hidden="true">
            <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"><path d="M4 12.5 9.5 18 20 6.5"></path></svg>
          </span>
        </span>
        <span class="disk-model">${escapeHtml(disk.model || "Unknown model")}</span>
        <span class="disk-tags">
          ${chip("subtle", disk.size_human || "size unknown")}
          ${typeChip}
        </span>
        <span class="meta-line mono trunc" title="${escapeHtml(mounted)}">${escapeHtml(mounted || "not mounted")}</span>
        ${warnings}
      </button>
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

  function planRow(label, value) {
    if (!value) {
      return "";
    }
    return `<div class="plan-key">${escapeHtml(label)}</div><div class="plan-val mono">${escapeHtml(value)}</div>`;
  }

  function planDetails(label, text) {
    if (!text) {
      return "";
    }
    return `<details class="plan-details"><summary>${escapeHtml(label)}</summary><pre>${escapeHtml(text)}</pre></details>`;
  }

  function planMarkup(payload) {
    const plan = payload.plan || {};
    const image = payload.image || {};
    const imagePath = image.cached_path || plan.base_image || image.url || "";
    const rows = [
      planRow("Node", plan.node),
      planRow("Hostname", plan.hostname),
      planRow("Role", plan.role),
      planRow("Target", plan.target),
      planRow("Device", plan.device),
      planRow("Image", imagePath),
      planRow("Version", image.version),
      planRow("SSH", plan.ssh),
      planRow("Boot payload", plan.boot_payload),
    ].join("");
    return [
      `<div class="plan-head">Flash plan</div>`,
      `<div class="plan-grid">${rows}</div>`,
      planDetails("Provision payload", payload.provision_display),
      planDetails("Boot files", payload.dry_run_info),
    ].join("");
  }

  function meshRadioCard(radio) {
    const host = radio.host || radio.address || "unknown";
    const title = radio.hostname || radio.expected_hostname || host;
    const status = radio.status === "connected" ? "connected" : radio.status || "seen";
    const rows = [
      meshDetail("Host", host),
      meshDetail("Address", radio.address),
      meshDetail("Node", radio.node),
      meshDetail("Expected IP", radio.expected_ip),
      meshDetail("Expected host", radio.expected_hostname),
      meshDetail("Status", status.replaceAll("_", " ")),
      meshDetail("Role", radio.role),
      meshDetail("Mesh", radio.mesh_id),
      meshDetail("Node IP", radio.node_ip),
      meshDetail("Target", radio.target),
      meshDetail("Source", radio.source),
      meshDetail("Error", radio.error || radio.stderr),
    ].filter(Boolean).join("");
    return `
      <article class="radio-card">
        <div class="radio-top">
          <div class="radio-title">
            <span class="radio-name mono">${escapeHtml(title)}</span>
            <span class="radio-sub mono">${escapeHtml(radio.summary || radio.address || "")}</span>
          </div>
          ${chip(radio.ok ? "ok" : "warn", status.replaceAll("_", " "))}
        </div>
        <div class="radio-details">${rows}</div>
      </article>
    `;
  }

  function meshNodeCard(node) {
    const title = node.name || node.hostname || node.ip || "unknown";
    const status = node.status || "seen";
    const rows = [
      meshDetail("Hostname", node.hostname),
      meshDetail("Role", node.role),
      meshDetail("IP", node.ip || node.node_ip),
      meshDetail("Target", node.target),
      meshDetail("Mesh MAC", node.mesh_mac),
      meshDetail("BAT0 MAC", node.bat0_mac),
      meshDetail("Status", status),
    ].filter(Boolean).join("");
    return `
      <article class="radio-card">
        <div class="radio-top">
          <div class="radio-title">
            <span class="radio-name mono">${escapeHtml(title)}</span>
            <span class="radio-sub mono">${escapeHtml(node.ip || node.node_ip || "")}</span>
          </div>
          ${chip(status === "online" || status === "connected" ? "ok" : "warn", status)}
        </div>
        <div class="radio-details">${rows}</div>
      </article>
    `;
  }

  function meshLinkRow(link) {
    const source = link.source || link.source_node || "unknown";
    const target = link.target || link.target_node || link.target_mac || "unresolved";
    const status = link.status || (link.target ? "resolved" : "unresolved");
    const meta = [link.iface, link.last_seen, link.throughput].filter(Boolean).join(" / ");
    return `
      <div class="topology-link">
        <span class="mono">${escapeHtml(source)}</span>
        <span aria-hidden="true">&rarr;</span>
        <span class="mono">${escapeHtml(target)}</span>
        ${chip(status === "resolved" ? "ok" : "warn", status)}
        <span class="meta-line mono">${escapeHtml(meta)}</span>
      </div>
    `;
  }

  function meshTopologyView(payload) {
    const nodes = payload.nodes || payload.radios || [];
    const links = payload.links || [];
    const nodeMarkup = nodes.map((node) => meshNodeCard(node)).join("");
    const linkMarkup = links.length
      ? `<div class="topology-links">${links.map((link) => meshLinkRow(link)).join("")}</div>`
      : `<div class="empty-state slim"><p class="empty-title">No links reported</p><p class="empty-meta">The gateway API did not report active BATMAN neighbors.</p></div>`;
    return `
      <div class="topology-section">
        <div class="mesh-grid">${nodeMarkup}</div>
      </div>
      <div class="topology-section">
        <div class="section-title">Links</div>
        ${linkMarkup}
      </div>
    `;
  }

  function meshDetail(label, value) {
    if (!value) {
      return "";
    }
    return `<span class="radio-key">${escapeHtml(label)}</span><span class="radio-value mono">${escapeHtml(value)}</span>`;
  }

  function meshDiscoveryMarkup(payload) {
    const rows = [];
    const checked = Number(payload.candidates_checked) || 0;
    const nodes = payload.nodes || payload.radios || [];
    const links = payload.links || [];
    if (payload.ok) {
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
    imageItem,
    diskCard,
    validationMarkup,
    planMarkup,
    meshRadioCard,
    meshNodeCard,
    meshTopologyView,
    meshDiscoveryMarkup,
  };
})();
