/* Sections 03 + 04 — BlackBox (inside the box) and IoT connections (outside it).
   The internal schematic mirrors the ULTRON hardware-twin idea: drawn cables,
   packet pulses on every event and lids that pop open on a detection. */
(() => {
  "use strict";
  const $ = (s) => document.querySelector(s);
  const BANDS = { GREEN: "#38bdf8", BLUE: "#4c8dff", YELLOW: "#f2c230", RED: "#ff4a3d", PURPLE: "#b45cff" };
  const ICONS = { ac: "❄", thermostat: "◉", camera: "◈", door: "▥", plug: "ϟ", light: "☀", fan: "✣", sensor: "◇", generic: "□" };
  const KIND_ORDER = { ac: 0, thermostat: 1, camera: 2, door: 3, plug: 4, light: 5, fan: 6, sensor: 7, generic: 8 };
  let S = null, selected = null, blackBuilt = false, pulses = [], lidTimer = null, lastEventTs = 0;

  const BOARDS = [
    { id: "sentinel", x: 14, y: 104, w: 122, h: 58, label: "PI 3 · SENTINEL", sub: "sniffer + USB log", lid: true },
    { id: "core", x: 149, y: 104, w: 122, h: 58, label: "PI 4 · CORE", sub: "threat engine + verify", lid: true },
    { id: "herald", x: 284, y: 104, w: 122, h: 58, label: "PI 3 · HERALD", sub: "SMTP alerts", lid: true },
    { id: "rig", x: 14, y: 214, w: 122, h: 52, label: "ESP32-WROOM", sub: "room rig · GPIO", lid: false },
    { id: "indicator", x: 149, y: 214, w: 122, h: 52, label: "ESP32-C3", sub: "OLED + NeoPixel", lid: false },
  ];
  const CABLES = [
    { d: "M75,104 C75,68 180,66 196,42", label: "LAN", from: "sentinel" },
    { d: "M210,104 L210,42", label: "LAN", from: "core" },
    { d: "M345,104 C345,68 240,66 224,42", label: "LAN", from: "herald" },
    { d: "M210,162 L210,214", label: "USB", from: "core" },
    { d: "M136,240 C96,240 92,170 132,140", label: "MQTT", from: "rig" },
  ];

  const fresh = (row) => row.observed && Date.now() / 1000 - Number(row.rx || 0) < 15;

  function list() {
    const rows = window.ReWatchDevices?.list?.();
    if (rows) return rows;
    return Object.entries(S?.telemetry || {}).map(([id, t]) => ({
      device: id, kind: t.kind || "generic", room: t.room || id, ip: t.ip || "unknown",
      firmware: t.firmware || "unknown", rx: t.rx, observed: true, actions: [], adapter: "observe-only",
    }));
  }

  // ── 03 BlackBox ──────────────────────────────────────────────────────────
  function buildBlackbox() {
    const host = $("#blackbox"); if (!host || blackBuilt) return;
    blackBuilt = true;
    const boards = BOARDS.map((b) => `
      <g class="bb-board" data-board="${b.id}">
        ${b.lid ? `<rect class="bb-lid" x="${b.x}" y="${b.y - 11}" width="${b.w}" height="11" rx="3"/>` : ""}
        <rect class="bb-body" x="${b.x}" y="${b.y}" width="${b.w}" height="${b.h}" rx="5"/>
        <circle class="bb-led" cx="${b.x + b.w - 11}" cy="${b.y + 11}" r="3.5"/>
        <text class="bb-label" x="${b.x + 8}" y="${b.y + b.h - 20}">${b.label}</text>
        <text class="bb-sub" x="${b.x + 8}" y="${b.y + b.h - 7}">${b.sub}</text>
        <text class="bb-detail" data-detail="${b.id}" x="${b.x + 8}" y="${b.y + 13}"></text>
      </g>`).join("");
    const cables = CABLES.map((c, i) => `
      <path class="bb-cable" data-cable="${i}" d="${c.d}"/>
      <circle class="bb-pulse" data-pulse="${i}" r="3" opacity="0"/>`).join("");
    const labels = CABLES.map((c) => {
      const mid = c.d.split(" ")[1] || "";
      return "";
    }).join("");
    host.innerHTML = `
      <svg viewBox="0 0 420 285" role="img" aria-label="ReWatch box internals and packet flow">
        <rect class="bb-switch" x="150" y="8" width="120" height="34" rx="5"/>
        <text class="bb-label" x="210" y="29" text-anchor="middle">ROUTER · SWITCH</text>
        ${cables}${boards}
        <rect class="bb-oled" x="222" y="236" width="40" height="20" rx="2"/>
        <text class="bb-sub" x="222" y="268">C3 OLED window</text>
        <text class="bb-sub" x="20" y="278" id="bb-flow">idle · no packets</text>
      </svg>`;
    pulses = [...host.querySelectorAll(".bb-pulse")];
  }

  function pulseCables() {
    const host = $("#blackbox"); if (!host) return;
    CABLES.forEach((cable, i) => {
      const path = host.querySelector(`.bb-cable[data-cable="${i}"]`);
      const dot = host.querySelector(`.bb-pulse[data-pulse="${i}"]`);
      if (!path || !dot) return;
      const len = path.getTotalLength();
      const t0 = performance.now();
      const run = (t) => {
        const k = Math.min(1, (t - t0) / 700);
        const p = path.getPointAtLength(len * (1 - k));
        dot.setAttribute("cx", p.x); dot.setAttribute("cy", p.y);
        dot.setAttribute("opacity", k < 1 ? "0.95" : "0");
        if (k < 1) requestAnimationFrame(run);
      };
      requestAnimationFrame(run);
    });
    const flow = $("#bb-flow");
    if (flow) flow.textContent = "packets flowing · bus → core → herald";
    clearTimeout(lidTimer);
    lidTimer = setTimeout(() => {
      for (const g of document.querySelectorAll(".bb-lid.open")) g.classList.remove("open");
      const flowEl = $("#bb-flow");
      if (flowEl) flowEl.textContent = "idle · no packets";
    }, 1400);
  }

  function openLids() {
    for (const g of document.querySelectorAll(".bb-lid")) g.classList.add("open");
  }

  function renderBlackbox() {
    const host = $("#blackbox"); if (!host || !S) return;
    buildBlackbox();
    for (const b of BOARDS) {
      const g = host.querySelector(`[data-board="${b.id}"]`); if (!g) continue;
      const h = S.nodes[b.id];
      const up = !!(h && h.online && Date.now() / 1000 - Number(h.rx || 0) < 20);
      g.classList.toggle("down", !up);
      const led = g.querySelector(".bb-led");
      if (led) led.setAttribute("fill", up ? (BANDS[S.band] || "#38bdf8") : "#ff4a3d");
      const detail = g.querySelector(`[data-detail="${b.id}"]`);
      if (!detail) continue;
      if (!h) detail.textContent = "no heartbeat";
      else if (b.id === "sentinel") detail.textContent = `usb ${h.usb ? "mounted" : "missing"} · ${h.logged_lines || 0} lines`;
      else if (b.id === "core") detail.textContent = `band ${h.band || "?"} · score ${h.score != null ? h.score : "?"}`;
      else if (b.id === "herald") detail.textContent = `smtp ${h.configured ? "ready" : "unset"}`;
      else if (b.id === "indicator") detail.textContent = `serial ${h.link ? "open" : "closed"}`;
      else detail.textContent = h.role || "rig";
    }
    const events = S.events || [];
    const newest = events.length ? events[events.length - 1] : null;
    if (newest && newest.ts > lastEventTs) {
      lastEventTs = newest.ts;
      pulseCables();
      if (["anomaly", "alert", "incident", "firmware-change", "slow-scan", "portscan", "arpsweep", "pingsweep", "flood"].includes(newest.kind)) {
        openLids();
      }
    }
  }

  // ── 04 IoT connections — modular flowchart, one node per device kind ────
  const KIND_NAME = { ac: "AC", thermostat: "Thermostat", camera: "IP camera", door: "Door",
    plug: "Plug", light: "Light", fan: "Fan", sensor: "Sensor", generic: "Device" };

  function kindSummary(kind, members) {
    const ips = members.map((m) => m.ip).filter((ip) => ip && ip !== "unknown");
    return `${(KIND_NAME[kind] || kind)} · ${members.length} device${members.length === 1 ? "" : "s"}\n`
      + members.map((m) => `· ${m.room || m.device} (${m.device})`).join("\n")
      + `\nIP: ${ips.length ? ips.join(", ") : "unknown"}`
      + `\nFirmware: ${[...new Set(members.map((m) => m.firmware))].join(", ")} (unattested)`;
  }

  function renderMap() {
    const host = $("#iotmap"); if (!host || !S) return;
    const rows = list();
    const groups = new Map();
    for (const row of rows) {
      const kind = row.kind || "generic";
      if (!groups.has(kind)) groups.set(kind, []);
      groups.get(kind).push(row);
    }
    const kinds = [...groups.keys()].sort((a, b) => (KIND_ORDER[a] ?? 8) - (KIND_ORDER[b] ?? 8));
    const boxX = 8, boxY = 118, boxW = 104, boxH = 58;
    const spineX = 150, nodeX = 186, nodeW = 224, nodeH = 32, top = 12, step = 40;
    const midY = boxY + boxH / 2;
    const parts = [];
    parts.push(`<rect class="im-box" x="${boxX}" y="${boxY}" width="${boxW}" height="${boxH}" rx="6"/>`);
    parts.push(`<text class="im-box-label" x="${boxX + boxW / 2}" y="${midY - 4}" text-anchor="middle">REWATCH</text>`);
    parts.push(`<text class="im-box-sub" x="${boxX + boxW / 2}" y="${midY + 12}" text-anchor="middle">box · 3 Pi + 2 ESP32</text>`);
    if (kinds.length) {
      const firstCy = top + nodeH / 2, lastCy = top + (kinds.length - 1) * step + nodeH / 2;
      parts.push(`<line class="im-bus" x1="${boxX + boxW}" y1="${midY}" x2="${spineX}" y2="${midY}"/>`);
      parts.push(`<line class="im-bus" x1="${spineX}" y1="${firstCy}" x2="${spineX}" y2="${lastCy}"/>`);
    }
    kinds.forEach((kind, i) => {
      const members = groups.get(kind);
      const y = top + i * step, cy = y + nodeH / 2;
      const up = members.some(fresh);
      const hot = (S.events || []).some((e) => e.device && members.some((m) => m.device === e.device)
        && Date.now() / 1000 - e.ts < 45);
      const sel = members.some((m) => m.device === selected);
      parts.push(`<line class="im-link ${hot ? "hot" : up ? "up" : "stale"}" x1="${spineX}" y1="${cy}" x2="${nodeX}" y2="${cy}"/>`);
      parts.push(`<g class="im-node im-kind${sel ? " selected" : ""}${up ? " up" : ""}" data-kind="${kind}" tabindex="0" role="button" aria-label="${KIND_NAME[kind] || kind}, ${members.length} devices">
        <title>${kindSummary(kind, members)}</title>
        <rect x="${nodeX}" y="${y}" width="${nodeW}" height="${nodeH}" rx="6"/>
        <text class="im-icon" x="${nodeX + 16}" y="${cy + 4}">${ICONS[kind] || ICONS.generic}</text>
        <text class="im-label" x="${nodeX + 34}" y="${cy - 2}">${KIND_NAME[kind] || kind}</text>
        <text class="im-ip" x="${nodeX + 34}" y="${cy + 10}">${members.length}× · ${short(members.map((m) => m.room || m.device).join(", "))}</text>
        <text class="im-ip" x="${nodeX + nodeW - 10}" y="${cy + 4}" text-anchor="end">${up ? "up" : "stale"}</text>
      </g>`);
    });
    host.innerHTML = `<svg viewBox="0 0 420 300" role="img" aria-label="External IoT device kinds connected to the ReWatch box">${parts.join("")}</svg>`;
    for (const node of host.querySelectorAll(".im-kind")) {
      node.addEventListener("click", () => pickKind(node.dataset.kind));
      node.addEventListener("keydown", (event) => {
        if (event.key === "Enter" || event.key === " ") { event.preventDefault(); pickKind(node.dataset.kind); }
      });
    }
    const sub = $("#iot-sub");
    if (sub) {
      const up = rows.filter(fresh).length;
      sub.textContent = rows.length
        ? `${kinds.length} kinds · ${rows.length} devices · ${up} reporting`
        : "no devices observed";
    }
  }

  function pickKind(kind) {
    const lead = list().find((row) => (row.kind || "generic") === kind);
    if (!lead) return;
    selected = lead.device;
    window.ReWatchDevices?.select?.(lead.device);
    renderMap();
  }

  const short = (s) => String(s || "").length > 16 ? String(s).slice(0, 15) + "…" : String(s || "");

  window.ReWatchTopology = {
    update(state) {
      S = state;
      renderBlackbox();
      renderMap();
    },
    select(device) { selected = device; renderMap(); },
  };
})();
