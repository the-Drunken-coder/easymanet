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
    const configuredSha = String(image.sha256 || "");
    const cachedSha = String(image.cached_sha256 || "");
    const cachedSize = formatBytes(image.cached_size_bytes);
    const lines = [
      `<div class="item-top"><span class="item-name mono">${escapeHtml(target)}</span>${chip(cached ? "ok" : "warn", cached ? "cached" : "will download")}</div>`,
      `<div class="meta-line">${escapeHtml(image.version || "unversioned")}</div>`,
    ];
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
          ${chip(disk.removable ? "ok" : "warn", disk.removable ? "removable" : "fixed")}
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

  function meshDetail(label, value) {
    if (!value) {
      return "";
    }
    return `<span class="radio-key">${escapeHtml(label)}</span><span class="radio-value mono">${escapeHtml(value)}</span>`;
  }

  function meshDiscoveryMarkup(payload) {
    const rows = [];
    const checked = Number(payload.candidates_checked) || 0;
    const radios = payload.radios || [];
    if (payload.ok) {
      rows.push(statusRow(radios.length ? "ok" : "subtle", `${radios.length} radios found`));
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
    meshDiscoveryMarkup,
  };
})();
