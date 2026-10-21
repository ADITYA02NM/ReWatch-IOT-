/* ReWatch IoT — live dashboard. Drives every panel from the WebSocket.
   Vanilla JS, hand-drawn canvas/SVG, no framework, no CDN. */
(() => {
  "use strict";
  const $ = (s, r = document) => r.querySelector(s);
  const el = (t, c, txt) => { const e = document.createElement(t); if (c) e.className = c; if (txt != null) e.textContent = txt; return e; };
  const clamp = (v, a, b) => Math.max(a, Math.min(b, v));
  const BANDS = { GREEN: "#38bdf8", BLUE: "#4c8dff", YELLOW: "#f2c230", RED: "#ff4a3d", PURPLE: "#b45cff" };

  // ── state ───────────────────────────────────────────────────────────────
  const S = {
    band: "BLUE", score: 0, reason: "", contrib: [], incident: null, thresholds: { yellow: 30, red: 70 },
    devices: {}, telemetry: {}, verify: {}, nodes: {}, history: [], events: [], mqtt: false, simulation: false,
    filter: "all", conn: "connecting", rate: 0, msgCount: 0, serverSkew: 0,
  };
  let ws = null, eventPage = 0;

  function briefingState(on) {
    const button = $("#btn-blackhat");
    if (button) { button.setAttribute("aria-pressed", String(!!on)); button.textContent = "Black Hat feed: " + (on ? "ON" : "OFF"); }
  }

  // ── websocket ───────────────────────────────────────────────────────────
  function connect() {
    const url = (location.protocol === "https:" ? "wss://" : "ws://") + location.host + "/ws";
    setConn("connecting");
    ws = new WebSocket(url);
    ws.onopen = () => { setConn("live"); pingLoop(); };
    ws.onclose = () => { setConn("offline"); ws = null; setTimeout(connect, 1500); };
    ws.onerror = () => { try { ws.close(); } catch {} };
    ws.onmessage = (ev) => {
      let m; try { m = JSON.parse(ev.data); } catch { return; }
      S.msgCount++;
      if (m.t === "hello") hydrate(m);
      else if (m.t === "bus") onBus(m.topic, m.d);
      else if (m.t === "event") pushEvent(m.e);
      else if (m.t === "mqtt") { S.mqtt = m.ok; }
      else if (m.t === "demo") briefingState(m.briefing);
      else if (m.t === "pong") S.serverSkew = (m.s * 1000) - Date.now();
    };
  }
  function pingLoop() {
    if (!ws || ws.readyState !== 1) return;
    ws.send(JSON.stringify({ op: "ping", c: Date.now() }));
    setTimeout(pingLoop, 5000);
  }
  function send(obj) { if (ws && ws.readyState === 1) ws.send(JSON.stringify(obj)); }

  function setConn(c) {
    S.conn = c;
    const p = $("#conn"); if (!p) return;
    p.className = "pill " + c;
    p.lastElementChild.textContent = c.toUpperCase();
  }

  function hydrate(m) {
    S.nodes = m.nodes || {}; S.telemetry = m.telemetry || {}; S.verify = m.verify || {};
    S.history = (m.history || []).slice(-600); S.events = (m.events || []).slice(-200);
    S.mqtt = m.mqtt; S.simulation = m.simulation === true;
    if ($("#mail-status")) $("#mail-status").textContent = (m.mail_status || "Preview only") + " · System summaries every 5 minutes.";
    if (m.version) $("#f-ver").textContent = "ReWatch IoT · SIMULATION · " + m.version;
    if (m.briefing != null) briefingState(m.briefing);
    if (m.state) applyState(m.state);
    renderEvents(); renderIncident(); renderAll();
  }

  function onBus(topic, d) {
    const p = topic.split("/");
    if (topic === "rewatch/threat/state") applyState(d);
    else if (p[1] === "health" && p[2]) { S.nodes[p[2]] = Object.assign({}, d, { rx: Date.now() / 1000 }); renderAll(); }
    else if (p[1] === "iot" && p[3] === "telemetry") { S.telemetry[p[2]] = Object.assign({}, d, { rx: Date.now() / 1000 }); renderAll(); }
    else if (p[1] === "verify" && p[2]) { S.verify[p[2]] = Object.assign({}, d, { rx: Date.now() / 1000 }); renderAll(); }
  }

  function applyState(st) {
    const prevBand = S.band;
    S.score = st.score || 0; S.reason = st.reason || ""; S.contrib = st.contrib || [];
    S.incident = st.incident || null; S.band = st.band || "BLUE";
    if (st.thresholds) S.thresholds = st.thresholds;
    if (st.devices) S.devices = st.devices;
    if (st.ts) { const tail = S.history[S.history.length - 1]; if (!tail || st.ts - tail[0] > 0.8) S.history.push([st.ts, S.score, S.band]); if (S.history.length > 600) S.history.shift(); }
    if (S.band !== prevBand) onBandChange(S.band);
    document.documentElement.setAttribute("data-band", S.band);
    renderAll();
  }

  function renderAll() {
    renderRisk(); renderIncident(); renderEvents();
    const demo = $("#btn-demo");
    if (demo) demo.textContent = rigBusy() ? "■ Simulate · AC stop" : "▶ Simulate · AC start/stop";
    window.ReWatchRisk?.update(S);
    window.ReWatchTopology?.update(S);
    window.ReWatchDevices?.update(S);
  }

  function onBandChange(b) {
    const f = $("#flash"); if (f) { f.classList.add("on"); setTimeout(() => f.classList.remove("on"), 260); }
    const names = { RED: "RED — critical threat", PURPLE: "PURPLE — automated response", YELLOW: "YELLOW — something to look at", BLUE: "BLUE — a node is offline", GREEN: "GREEN — all clear" };
    if (b === "RED" || b === "PURPLE") toast(names[b]);
  }

  // ── 01 risk ─────────────────────────────────────────────────────────────
  function renderRisk() {
    const bp = $("#bandpill"); if (bp) bp.lastElementChild.textContent = S.band;
    const sub = $("#risk-sub"); if (sub) sub.textContent = S.band === "BLUE" ? "a node is offline" : "score 0–100";
    const reason = $("#reason"); if (reason) reason.textContent = S.reason || "All quiet — nothing above noise.";
    renderContrib();
  }

  function renderContrib() {
    const box = $("#contrib"); if (!box) return;
    box.innerHTML = "";
    const inputs = S.contrib.filter((x) => (x.points || 0) > 0.5);
    const c = inputs.slice(0, 3);
    const meta = $("#eng-meta"); if (meta) meta.textContent = inputs.length > 3 ? "top 3 / " + inputs.length + " inputs" : "½-life 60 s";
    if (!c.length) { box.append(el("div", "quiet", "No active inputs — the score is at rest.")); return; }
    const max = Math.max(...c.map((x) => x.points), 1);
    for (const x of c) {
      box.append(el("span", "k", (x.src || "").toUpperCase()));
      const bar = el("div", "bar"); const i = el("i"); i.style.width = clamp(x.points / max * 100, 4, 100) + "%"; bar.appendChild(i); box.appendChild(bar);
      box.append(el("span", "v", Math.round(x.points)));
    }
  }

  // ── 02 alerts ───────────────────────────────────────────────────────────
  function pushEvent(e) {
    S.events.push(e); if (S.events.length > 250) S.events.shift(); renderEvents();
    if (e.kind === "mail" && $("#mail-status")) $("#mail-status").textContent = e.title + " · Summaries every 5 minutes.";
  }

  function renderEvents() {
    const ul = $("#feed"); if (!ul) return;
    const f = S.filter;
    const match = (e) => f === "all" ? true
      : f === "detect" ? ["portscan", "arpsweep", "pingsweep", "flood", "newdevice", "anomaly", "integrity", "device-offline", "firmware-change", "slow-scan"].includes(e.kind)
      : f === "incident" ? ["alert", "incident", "action", "command"].includes(e.kind)
      : f === "mail" ? e.kind === "mail"
      : f === "system" ? ["node", "rig", "summary"].includes(e.kind) : true;
    const matches = S.events.filter(match).reverse();
    const pages = Math.max(1, Math.ceil(matches.length / 3));
    eventPage = Math.min(eventPage, pages - 1);
    const list = matches.slice(eventPage * 3, eventPage * 3 + 3);
    const count = $("#ev-count"); if (count) count.textContent = matches.length + " events";
    const label = $("#events-page"); if (label) label.textContent = (matches.length ? eventPage + 1 : 0) + " / " + (matches.length ? pages : 0);
    const prev = $("#events-prev"), next = $("#events-next");
    if (prev) prev.disabled = eventPage === 0;
    if (next) next.disabled = eventPage + 1 >= pages;
    ul.innerHTML = "";
    for (const e of list) {
      const li = el("li", "s-" + (e.sev || "info") + " k-" + e.kind);
      li.innerHTML = `<span class="d"></span><span class="tm">${hms(e.ts)}</span><span class="tx">${esc(e.title)}</span>`;
      li.append(ackButton(e));
      ul.appendChild(li);
    }
    if (!list.length) ul.innerHTML = `<li style="grid-template-columns:1fr"><span class="tx dim" style="font-style:italic">Nothing here yet.</span></li>`;
  }

  /* Every incident-backed alert can be acknowledged from the feed. */
  function ackButton(e) {
    const wrap = el("span", "ack-wrap");
    if (!e.incident) { wrap.append(el("span", "ack-none", "—")); return wrap; }
    const live = S.incident && S.incident.state === "open" && S.incident.id === e.incident;
    const acked = S.incident && S.incident.id === e.incident && S.incident.state !== "open";
    const button = el("button", "btn ack-btn", acked ? "ACKED" : "ACK");
    button.type = "button";
    button.disabled = !live;
    button.title = live ? "Acknowledge this incident (cancels automatic response)"
      : acked ? "Incident already handled" : "This incident is no longer open";
    button.addEventListener("click", () => {
      send({ op: "ack", id: e.incident });
      toast("Acknowledged — automatic response cancelled");
    });
    wrap.append(button);
    return wrap;
  }

  function renderIncident() {
    const box = $("#inc"); if (!box) return;
    const inc = S.incident; const incId = $("#inc-id"); if (incId) incId.textContent = inc ? inc.id : "";
    if (!inc || inc.state === "resolved") { box.innerHTML = calmHtml(); return; }
    const total = (inc.deadline - inc.opened) || 20;
    const frac = inc.state === "open" ? clamp((inc.remaining || 0) / total, 0, 1) : (inc.state === "acked" ? 1 : 0);
    const steps = [
      ["Detect", true], ["Alert requested", true],
      ["Acknowledge", inc.state === "acked", inc.state === "open"],
      ["Auto-respond", inc.state === "auto", false],
    ];
    const act = inc.action ? `<p class="mono">↳ ${esc(inc.action.summary)}</p>` : "";
    box.innerHTML = `
      <div class="inc-body">
        <div class="ring">${ringSvg(frac, inc.state)}<div class="rv"><b id="cd">${inc.state === "open" ? Math.ceil(inc.remaining || 0) : "•"}</b><span>${inc.state === "open" ? "sec left" : inc.state}</span></div></div>
        <div class="inc-txt"><h3>${esc(inc.title)}</h3>
          <p>${inc.device ? "Device " + esc(inc.device) : inc.src ? "Source " + esc(inc.src) : "critical risk"} · peak ${Math.round(inc.peak || 0)}/100</p>
          <div class="steps">${steps.map((s) => `<div class="step ${s[1] ? "done" : ""} ${s[2] ? "now" : ""}"><b>${s[0]}</b>${s[1] ? "done" : s[2] ? "waiting" : "—"}</div>`).join("")}</div>
          ${act}
        </div>
      </div>
      <div class="inc-act">
        <button class="btn primary" id="ack" ${inc.state === "open" ? "" : "disabled"}>Acknowledge</button>
        <button class="btn" id="respond" ${inc.state === "open" ? "" : "disabled"}>Respond now</button>
      </div>`;
    $("#ack")?.addEventListener("click", () => { send({ op: "ack", id: inc.id }); toast("Acknowledged — automation cancelled"); });
    $("#respond")?.addEventListener("click", () => { send({ op: "respond", id: inc.id }); toast("Running the response now"); });
  }

  function calmHtml() {
    return `<div class="calm"><svg class="shield" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.4"><path d="M12 3l7 3v5c0 4.4-3 8.3-7 10-4-1.7-7-5.6-7-10V6z"/><path d="M8.5 12l2.5 2.5L15.5 10"/></svg><div><h3>All clear</h3><p>No open incident. The engine scores every input live; In this simulation, RED opens an incident with a 20-second countdown. Production defaults to 120 seconds.</p></div></div>`;
  }
  function ringSvg(frac, state) {
    const r = 66, c = 2 * Math.PI * r, col = state === "acked" ? BANDS.GREEN : (state === "auto" ? BANDS.PURPLE : BANDS.RED);
    return `<svg viewBox="0 0 150 150"><circle cx="75" cy="75" r="${r}" stroke="rgba(255,255,255,.08)" stroke-width="8" fill="none"/><circle cx="75" cy="75" r="${r}" stroke="${col}" stroke-width="8" fill="none" stroke-linecap="round" stroke-dasharray="${c}" stroke-dashoffset="${c * (1 - frac)}" style="transition:stroke-dashoffset .5s,stroke .4s"/></svg>`;
  }

  // ── OLED twin + LED ─────────────────────────────────────────────────────
  function drawOled() {
    const cv = $("#oled"); if (!cv) return; const g = cv.getContext("2d");
    g.fillStyle = "#040d1a"; g.fillRect(0, 0, 128, 64);
    const fresh = S.conn === "live" && (S.mqtt || S.simulation);
    const sigCol = BANDS[S.band] || "#38bdf8";
    g.fillStyle = sigCol;
    if (!fresh) { oledText(g, "ReWatch", 2, 2); oledText(g, "link lost", 34, 30); drawZ(g); return; }
    g.font = "bold 8px monospace"; oledText(g, "ReWatch", 0, 1);
    g.fillRect(0, 10, 128, 1);
    const order = ["core", "sentinel", "herald", "rig"], lab = ["P4", "3A", "3B", "RG"];
    for (let i = 0; i < 4; i++) {
      const x = (i % 2) * 24, y = 13 + ((i / 2) | 0) * 15, up = isUp(order[i]);
      if (up) { g.fillStyle = sigCol; g.fillRect(x, y, 22, 13); g.fillStyle = "#040d1a"; }
      else { g.strokeStyle = sigCol; g.strokeRect(x + .5, y + .5, 21, 12); g.fillStyle = sigCol; }
      g.font = "8px monospace"; g.fillText(lab[i], x + 4, y + 10);
    }
    g.fillStyle = sigCol; g.font = "bold 26px monospace";
    g.fillText(String(Math.round(S.score)).padStart(3, " "), 56, 36);
    g.font = "8px monospace";
    const word = { RED: "ALERT", PURPLE: "LOCKDOWN", YELLOW: "DETECT", GREEN: "NORMAL", BLUE: "OFFLINE" }[S.band] || "OFFLINE";
    g.fillText(word, 56, 44);
    drawEcg(g, S.band, sigCol);
  }
  function oledText(g, t, x, y) { g.font = "8px monospace"; g.fillText(t, x, y + 8); }
  function drawZ(g) { g.font = "7px monospace"; g.fillText("z", 108, 20); g.fillText("z", 116, 14); }
  function drawEcg(g, band, sigCol) {
    const base = 59, pitch = { YELLOW: 128, RED: 64, PURPLE: 32 }[band] || 0;
    g.strokeStyle = sigCol || "#38bdf8"; g.beginPath(); g.moveTo(0, base); g.lineTo(128, base); g.stroke();
    if (!pitch) return;
    const scroll = Math.floor(Date.now() / 60) % pitch;
    const knots = [[0, 0], [.08, 0], [.13, 3], [.18, 0], [.22, -2], [.25, 11], [.28, -4], [.32, 0], [.40, 0], [.47, 5], [.56, 0], [1, 0]];
    const defl = (p) => { const t = (p % pitch) / pitch; for (let i = 1; i < knots.length; i++) { if (t <= knots[i][0]) { const s = knots[i][0] - knots[i - 1][0], u = s > 0 ? (t - knots[i - 1][0]) / s : 0; return knots[i - 1][1] * (1 - u) + knots[i][1] * u; } } return 0; };
    g.beginPath();
    for (let x = 0; x < 128; x++) { const y = base - defl(x + scroll); x ? g.lineTo(x, y) : g.moveTo(x, y); }
    g.stroke();
  }
  function isUp(n) { const h = S.nodes[n]; return !!(h && h.online && (Date.now() / 1000 - (h.rx || 0)) < 20); }

  function drawNeo() {
    const i = $("#neo"), w = $("#neo-word"); if (!i) return;
    const fresh = S.conn === "live";
    const col = fresh ? (BANDS[S.band] || BANDS.BLUE) : BANDS.BLUE;
    const period = { GREEN: 0, YELLOW: 500, RED: 250, PURPLE: 1000, BLUE: 2000 }[fresh ? S.band : "BLUE"];
    const lit = period === 0 ? true : (Math.floor(Date.now() / (period / 2)) & 1) === 1;
    i.style.background = lit ? col : "#111";
    i.style.boxShadow = lit ? "0 0 14px " + col : "none";
    const words = { GREEN: "cyan · all clear", YELLOW: "yellow · 2 Hz", RED: "red · 4 Hz blink", PURPLE: "purple · 1 Hz", BLUE: "blue · no link" };
    w.textContent = words[fresh ? S.band : "BLUE"];
  }

  // ── 05 controls: export, refresh, clear, OLED preview ──────────────────
  async function exportMarkdown() {
    let report = {};
    try {
      const response = await fetch("/api/report?hours=5", { credentials: "same-origin" });
      if (response.ok) report = await response.json();
    } catch { report = {}; }
    const stamp = new Date().toISOString();
    const events = report.events || S.events || [];
    const incidents = report.incidents || [];
    const devices = report.devices || [];
    const lines = [];
    lines.push("# ReWatch IoT — evidence export");
    lines.push("");
    lines.push(`- generated: ${stamp}`);
    lines.push(`- source: ${location.origin}/api/report (last ${report.hours || 5} hours)`);
    lines.push(`- mode: ${report.simulation ? "simulation (synthetic)" : "live"} · MQTT broker: ${S.mqtt ? "connected" : "not connected"}`);
    lines.push(`- band: ${S.band} · score: ${Math.round(S.score)}/100 · open incident: ${S.incident && S.incident.state !== "resolved" ? S.incident.id : "none"}`);
    lines.push("");
    lines.push("## Incidents");
    lines.push("");
    if (!incidents.length) lines.push("_no incidents recorded in this window_");
    else {
      lines.push("| incident | opened | state | peak | device | title |");
      lines.push("| --- | --- | --- | --- | --- | --- |");
      for (const i of incidents) {
        lines.push(`| ${i.id || ""} | ${i.opened ? new Date(i.opened * 1000).toISOString() : ""} | ${i.state || ""} | ${i.peak ?? ""} | ${i.device || ""} | ${String(i.title || "").replace(/\|/g, "/")} |`);
      }
    }
    lines.push("");
    lines.push("## Events");
    lines.push("");
    if (!events.length) lines.push("_no events recorded in this window_");
    else {
      lines.push("| time | kind | severity | node | device | title |");
      lines.push("| --- | --- | --- | --- | --- | --- |");
      for (const e of events) {
        const time = e.ts ? new Date(e.ts * 1000).toISOString() : "";
        lines.push(`| ${time} | ${e.kind || ""} | ${e.sev || ""} | ${e.node || ""} | ${e.device || ""} | ${String(e.title || "").replace(/\|/g, "/")} |`);
      }
    }
    lines.push("");
    lines.push("## Devices");
    lines.push("");
    if (!devices.length) lines.push("_no device inventory in this window_");
    else {
      lines.push("| device | kind | room | ip | firmware |");
      lines.push("| --- | --- | --- | --- | --- |");
      for (const d of devices) {
        lines.push(`| ${d.device || ""} | ${d.kind || ""} | ${d.room || ""} | ${d.ip || ""} | ${d.firmware || ""} |`);
      }
    }
    lines.push("");
    lines.push("## Caveats");
    lines.push("");
    lines.push("- SMTP acceptance is not delivery confirmation; the transport only reports the server accepted the message.");
    lines.push("- Only traffic the Sentinel can observe is analysed; on a plain switch that needs SPAN/TAP or a mirrored port.");
    lines.push("- Reported firmware strings and IPs are device-reported, not attested.");
    if (report.simulation) lines.push("- This export was produced by the simulation: the devices and events are synthetic.");
    lines.push("");
    const blob = new Blob([lines.join("\n")], { type: "text/markdown;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url; a.download = `rewatch-evidence-${stamp.replace(/[:.]/g, "-")}.md`;
    document.body.appendChild(a); a.click(); a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 4000);
    toast("Evidence exported as Markdown");
  }

  async function refreshLinks() {
    const note = $("#ctl-note");
    if (note) note.textContent = "re-checking every connection…";
    try {
      await fetch("/api/devices", { credentials: "same-origin", cache: "no-store" });
      await fetch("/api/state", { credentials: "same-origin", cache: "no-store" });
      send({ op: "ping", c: Date.now() });
    } catch { /* offline: the panels keep their last known state */ }
    renderAll();
    if (note) note.textContent = `links re-checked · ${Object.keys(S.telemetry).length} devices reporting · MQTT ${S.mqtt ? "connected" : "offline"}`;
    toast("Connections re-checked");
  }

  function clearView() {
    S.events = [];
    eventPage = 0;
    renderEvents();
    window.ReWatchDevices?.select?.(null);
    send({ op: "rig", scenario: "reset" });
    toast("Feed cleared and setpoints reset — stored evidence is untouched");
  }

  // ── footer / clock ──────────────────────────────────────────────────────
  function tick() {
    const d = new Date(Date.now() + S.serverSkew);
    const clock = $("#clock"); if (clock) clock.textContent = d.toLocaleTimeString("en-GB", { hour12: false });
    if (S.incident && S.incident.state === "open") {
      const cd = $("#cd"); if (cd) { const left = Math.max(0, (S.incident.deadline - (Date.now() + S.serverSkew) / 1000)); cd.textContent = Math.ceil(left); }
    }
    S.rate = S.msgCount; const rate = $("#f-rate"); if (rate) rate.textContent = S.rate; S.msgCount = 0;
    const ev = $("#f-events"); if (ev) ev.textContent = S.events.length;
    const open = $("#f-open"); if (open) open.textContent = S.incident && S.incident.state !== "resolved" ? 1 : 0;
  }
  function raf() { drawOled(); drawNeo(); requestAnimationFrame(raf); }

  // ── misc ────────────────────────────────────────────────────────────────
  function esc(s) { return String(s == null ? "" : s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c])); }
  function hms(ts) { return new Date((ts || 0) * 1000).toLocaleTimeString("en-GB", { hour12: false }); }
  function toast(t) { const box = $("#toast"); const d = el("div", null, t); box.appendChild(d); setTimeout(() => d.remove(), 5000); }

  // chips + pager
  $("#chips")?.addEventListener("click", (e) => {
    const b = e.target.closest("button"); if (!b) return;
    S.filter = b.dataset.f; eventPage = 0;
    for (const x of $("#chips").children) x.classList.toggle("on", x === b);
    renderEvents();
  });
  $("#events-prev")?.addEventListener("click", () => { eventPage = Math.max(0, eventPage - 1); renderEvents(); });
  $("#events-next")?.addEventListener("click", () => { eventPage++; renderEvents(); });
  /* The rig drill button follows the rig's observed state: it spikes a calm
     AC and restores an elevated one, so it never needs a separate reset. */
  function rigBusy() {
    const tel = S.telemetry["room1-ac"] || {};
    const temp = Number(tel.temp_c);
    return Number.isFinite(temp) && temp > 22;
  }
  $("#btn-demo")?.addEventListener("click", () => {
    const busy = rigBusy();
    send({ op: "rig", scenario: busy ? "reset" : "ac-spike", device: "room1-ac" });
    toast(busy ? "Simulated Room 1 setpoint restored" : "Simulated AC spike started on Room 1");
  });
  $("#btn-mail")?.addEventListener("click", () => { send({ op: "mail-test" }); toast("Mail preview/test requested — the result lands in the alert feed"); });
  $("#btn-replay")?.addEventListener("click", () => { send({ op: "replay" }); toast("Replay restarted: discovery 20 s, spike 30 s"); });
  $("#btn-blackhat")?.addEventListener("click", () => { send({ op: "briefing" }); toast("Toggled the synthetic detection feed — no network attacks run"); });
  $("#btn-firmware")?.addEventListener("click", () => { send({ op: "firmware-demo" }); toast("Simulated reported firmware changed — not attestation"); });
  $("#btn-export")?.addEventListener("click", exportMarkdown);
  $("#btn-refresh")?.addEventListener("click", refreshLinks);
  $("#btn-clear")?.addEventListener("click", clearView);
  $("#btn-oled")?.addEventListener("click", () => {
    const box = $("#oled-preview");
    if (!box) return;
    const open = box.hasAttribute("hidden");
    box.toggleAttribute("hidden", !open);
    $("#btn-oled").setAttribute("aria-expanded", String(open));
  });
  $("#lock-btn")?.addEventListener("click", async () => { await window.ReWatchAuth.logout(); location.reload(); });

  // Ctrl+Shift+R or Cmd+Shift+R resets everything: score, color, incident, and logs
  window.addEventListener("keydown", (e) => {
    if ((e.ctrlKey || e.metaKey) && e.shiftKey && (e.key === "R" || e.key === "r")) {
      e.preventDefault();
      eventPage = 0;
      S.events = [];
      S.history = [];
      S.score = 0;
      S.band = "GREEN";
      S.reason = "All quiet — reset requested.";
      S.incident = null;
      document.documentElement.setAttribute("data-band", "GREEN");
      renderAll();
      send({ op: "replay" });
      toast("Reset everything: score, color, and logs cleared");
    }
  }, true);

  window.ReWatch = {
    start() {
      if (ws) return;
      connect();
      setInterval(tick, 500); tick();
      requestAnimationFrame(raf);
      setInterval(renderIncident, 1000);
      window.ReWatchRisk?.bind?.();
    },
  };
})();
