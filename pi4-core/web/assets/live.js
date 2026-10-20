/* ReWatch IoT — live dashboard. Drives every panel from the WebSocket.
   Vanilla JS, hand-drawn canvas/SVG, no framework, no CDN. */
(() => {
  "use strict";
  const $ = (s, r = document) => r.querySelector(s);
  const el = (t, c, txt) => { const e = document.createElement(t); if (c) e.className = c; if (txt != null) e.textContent = txt; return e; };
  const clamp = (v, a, b) => Math.max(a, Math.min(b, v));
  const BANDS = { GREEN: "#34d27b", BLUE: "#4c8dff", YELLOW: "#f2c230", RED: "#ff4a3d", PURPLE: "#b45cff" };
  const NODE_META = {
    core: ["Pi 4 · Core", "threat engine · port 3"],
    sentinel: ["Pi 3 · Sentinel", "detect + usb log · port 2"],
    herald: ["Pi 3 · Herald", "smtp alerts · port 4"],
    indicator: ["ESP32-C3", "oled + neopixel"],
    rig: ["ESP32-WROOM", "room rig"],
    verifier: ["Pi 4 · Verify", "wi-fi cross-check"],
  };

  // ── state ───────────────────────────────────────────────────────────────
  const S = {
    band: "BLUE", score: 0, reason: "", contrib: [], incident: null, thresholds: { yellow: 30, red: 70 },
    devices: {}, telemetry: {}, verify: {}, nodes: {}, history: [], events: [], mqtt: false,
    filter: "all", conn: "connecting", rate: 0, msgCount: 0, serverSkew: 0,
  };
  let ws = null, roomSpark = {};

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
    S.mqtt = m.mqtt; if (m.version) $("#f-ver").textContent = "ReWatch IoT · v" + m.version;
    if (m.state) applyState(m.state);
    renderEvents(); renderFleet(); renderRooms(); renderTopo();
  }

  function onBus(topic, d) {
    const p = topic.split("/");
    if (topic === "rewatch/threat/state") applyState(d);
    else if (p[1] === "health" && p[2]) { S.nodes[p[2]] = Object.assign({}, d, { rx: Date.now() / 1000 }); renderFleet(); renderTopo(); }
    else if (p[1] === "iot" && p[3] === "telemetry") { S.telemetry[p[2]] = Object.assign({}, d, { rx: Date.now() / 1000 }); renderRooms(); }
    else if (p[1] === "verify" && p[2]) { S.verify[p[2]] = Object.assign({}, d, { rx: Date.now() / 1000 }); renderRooms(); }
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
    renderRisk(); renderIncident(); renderRooms(); renderTopo(); renderFleet();
  }

  function onBandChange(b) {
    const f = $("#flash"); if (f) { f.classList.add("on"); setTimeout(() => f.classList.remove("on"), 260); }
    const names = { RED: "RED — critical threat", PURPLE: "PURPLE — automated response", YELLOW: "YELLOW — something to look at", BLUE: "BLUE — a node is offline", GREEN: "GREEN — all clear" };
    if (b === "RED" || b === "PURPLE") toast(names[b]);
  }

  // ── risk panel ──────────────────────────────────────────────────────────
  function renderRisk() {
    $("#score").innerHTML = Math.round(S.score) + '<small>/100</small>';
    $("#bandword").textContent = S.band;
    $("#reason").textContent = S.reason || "All quiet — nothing above noise.";
    const bp = $("#bandpill"); bp.lastElementChild.textContent = S.band;
    $("#risk-sub").textContent = S.band === "BLUE" ? "a node is offline" : "score 0–100";
    const needle = $("#needle"); if (needle) needle.style.left = clamp(S.score, 0, 100) + "%";
    renderContrib(); drawGraph();
  }

  function renderContrib() {
    const box = $("#contrib"); box.innerHTML = "";
    const c = S.contrib.filter((x) => (x.points || 0) > 0.5).slice(0, 5);
    if (!c.length) { const q = el("div", "quiet", "No active inputs — the score is at rest."); box.appendChild(q); return; }
    const max = Math.max(...c.map((x) => x.points), 1);
    for (const x of c) {
      box.appendChild(el("span", "k", (x.src || "").toUpperCase()));
      const bar = el("div", "bar"); const i = el("i"); i.style.width = clamp(x.points / max * 100, 4, 100) + "%"; bar.appendChild(i); box.appendChild(bar);
      box.appendChild(el("span", "v", Math.round(x.points)));
      if (x.title) box.appendChild(el("span", "t", x.title));
    }
  }

  function drawGraph() {
    const cv = $("#graph"); if (!cv) return;
    const dpr = window.devicePixelRatio || 1, w = cv.clientWidth, h = cv.clientHeight;
    if (cv.width !== w * dpr) { cv.width = w * dpr; cv.height = h * dpr; }
    const g = cv.getContext("2d"); g.setTransform(dpr, 0, 0, dpr, 0, 0); g.clearRect(0, 0, w, h);
    // band threshold guides
    for (const [val, col] of [[S.thresholds.yellow, BANDS.YELLOW], [S.thresholds.red, BANDS.RED]]) {
      const y = h - (val / 100) * h; g.strokeStyle = col + "33"; g.setLineDash([3, 4]); g.beginPath(); g.moveTo(0, y); g.lineTo(w, y); g.stroke();
    }
    g.setLineDash([]);
    const hist = S.history; if (hist.length < 2) return;
    const t0 = hist[0][0], t1 = hist[hist.length - 1][0], span = Math.max(t1 - t0, 1);
    const X = (t) => (t - t0) / span * w, Y = (v) => h - (clamp(v, 0, 100) / 100) * h;
    // filled area
    g.beginPath(); g.moveTo(X(hist[0][0]), h);
    for (const p of hist) g.lineTo(X(p[0]), Y(p[1]));
    g.lineTo(X(t1), h); g.closePath();
    const grd = g.createLinearGradient(0, 0, 0, h); const ac = BANDS[S.band] || BANDS.GREEN;
    grd.addColorStop(0, ac + "55"); grd.addColorStop(1, ac + "05"); g.fillStyle = grd; g.fill();
    // coloured line per band segment
    g.lineWidth = 1.8; g.lineJoin = "round";
    for (let i = 1; i < hist.length; i++) {
      g.strokeStyle = BANDS[hist[i][2]] || BANDS.GREEN; g.beginPath();
      g.moveTo(X(hist[i - 1][0]), Y(hist[i - 1][1])); g.lineTo(X(hist[i][0]), Y(hist[i][1])); g.stroke();
    }
    // head dot
    const last = hist[hist.length - 1]; g.fillStyle = BANDS[last[2]] || BANDS.GREEN;
    g.beginPath(); g.arc(X(last[0]), Y(last[1]), 3, 0, 7); g.fill();
    $("#gleg").textContent = Math.round(span / 60) + " min · " + hist.length + " samples";
  }

  // ── incident panel + OLED twin ──────────────────────────────────────────
  function renderIncident() {
    const box = $("#inc"), inc = S.incident; $("#inc-id").textContent = inc ? inc.id : "";
    if (!inc || inc.state === "resolved") { box.innerHTML = calmHtml(); return; }
    const total = (inc.deadline - inc.opened) || 120;
    const frac = inc.state === "open" ? clamp((inc.remaining || 0) / total, 0, 1) : (inc.state === "acked" ? 1 : 0);
    const steps = [
      ["Detect", true], ["Alert e-mail", true],
      ["Acknowledge", inc.state === "acked", inc.state === "open"],
      ["Auto-respond", inc.state === "auto", false],
    ];
    const act = inc.action ? `<p class="mono" style="margin:8px 0 0;color:var(--muted)">↳ ${esc(inc.action.summary)}</p>` : "";
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
    return `<div class="calm"><svg class="shield" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.4"><path d="M12 3l7 3v5c0 4.4-3 8.3-7 10-4-1.7-7-5.6-7-10V6z"/><path d="M8.5 12l2.5 2.5L15.5 10"/></svg><div><h3>All clear</h3><p>No open incident. The engine is scoring every input live; a RED crossing opens one here with a 2-minute countdown.</p></div></div>`;
  }
  function ringSvg(frac, state) {
    const r = 66, c = 2 * Math.PI * r, col = state === "acked" ? BANDS.GREEN : (state === "auto" ? BANDS.PURPLE : BANDS.RED);
    return `<svg viewBox="0 0 150 150"><circle cx="75" cy="75" r="${r}" stroke="rgba(255,255,255,.08)" stroke-width="8" fill="none"/><circle cx="75" cy="75" r="${r}" stroke="${col}" stroke-width="8" fill="none" stroke-linecap="round" stroke-dasharray="${c}" stroke-dashoffset="${c * (1 - frac)}" style="transition:stroke-dashoffset .5s,stroke .4s"/></svg>`;
  }

  function drawOled() {
    const cv = $("#oled"); if (!cv) return; const g = cv.getContext("2d");
    g.fillStyle = "#04120a"; g.fillRect(0, 0, 128, 64);
    const fresh = S.conn === "live" && S.mqtt;
    g.fillStyle = "#39e08a";
    if (!fresh) { oledText(g, "ReWatch", 2, 2); oledText(g, "link lost", 34, 30); drawZ(g); return; }
    g.font = "bold 8px monospace"; oledText(g, "ReWatch", 0, 1);
    g.fillRect(0, 10, 128, 1);
    // fleet 2x2
    const order = ["core", "sentinel", "herald", "rig"], lab = ["P4", "3A", "3B", "RG"];
    for (let i = 0; i < 4; i++) {
      const x = (i % 2) * 24, y = 13 + ((i / 2) | 0) * 15, up = isUp(order[i]);
      if (up) { g.fillStyle = "#39e08a"; g.fillRect(x, y, 22, 13); g.fillStyle = "#04120a"; }
      else { g.strokeStyle = "#39e08a"; g.strokeRect(x + .5, y + .5, 21, 12); g.fillStyle = "#39e08a"; }
      g.font = "8px monospace"; g.fillText(lab[i], x + 4, y + 10);
    }
    // score
    g.fillStyle = "#39e08a"; g.font = "bold 26px monospace";
    g.fillText(String(Math.round(S.score)).padStart(3, " "), 56, 36);
    g.font = "8px monospace";
    const word = { RED: "ALERT", PURPLE: "LOCKDOWN", YELLOW: "DETECT", GREEN: "NORMAL", BLUE: "OFFLINE" }[S.band] || "OFFLINE";
    g.fillText(word, 56, 44);
    drawEcg(g, S.band);
  }
  function oledText(g, t, x, y) { g.font = "8px monospace"; g.fillText(t, x, y + 8); }
  function drawZ(g) { g.font = "7px monospace"; g.fillText("z", 108, 20); g.fillText("z", 116, 14); }
  function drawEcg(g, band) {
    const base = 59, pitch = { YELLOW: 128, RED: 64, PURPLE: 32 }[band] || 0;
    g.strokeStyle = "#39e08a"; g.beginPath(); g.moveTo(0, base); g.lineTo(128, base); g.stroke();
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
    const words = { GREEN: "green · all clear", YELLOW: "yellow · 2 Hz", RED: "red · 4 Hz blink", PURPLE: "purple · 1 Hz", BLUE: "blue · no link" };
    w.textContent = words[fresh ? S.band : "BLUE"];
  }

  // ── rooms ───────────────────────────────────────────────────────────────
  function renderRooms() {
    const box = $("#rooms"); if (!box) return;
    const keys = Object.keys(S.telemetry).sort();
    $("#rooms-sub").textContent = keys.length ? keys.length + " online" : "";
    if (!keys.length) { box.innerHTML = `<div class="empty" style="grid-column:1/-1">No IoT devices reporting yet.<br><code>rewatch/iot/&lt;device&gt;/telemetry</code></div>`; return; }
    box.innerHTML = "";
    for (const k of keys) {
      const t = S.telemetry[k], v = S.verify[k] || {}, dev = S.devices[k] || {};
      const level = dev.level || "ok", offline = (Date.now() / 1000 - (t.rx || 0)) > 15;
      const card = el("div", "room " + (offline ? "off" : level));
      const temp = typeof t.temp_c === "number" ? t.temp_c.toFixed(1) : "—";
      const vch = v.ok === true ? '<span class="vchip ok">wifi ✓</span>' : v.ok === false ? '<span class="vchip bad">wifi ✗</span>' : '<span class="vchip">wifi —</span>';
      card.innerHTML = `<div class="rn"><span>${esc(t.room || k)}</span>${vch}</div>
        <div class="rt">${temp}<small>°C</small></div>
        <div class="rs"><span>set ${t.setpoint != null ? t.setpoint + "°" : "—"}</span><span>${t.power || (offline ? "offline" : "on")}</span></div>
        <canvas width="200" height="36"></canvas>`;
      box.appendChild(card);
      sparkRoom(card.querySelector("canvas"), k, level);
    }
  }
  function sparkRoom(cv, key, level) {
    const hist = roomSpark[key] = (roomSpark[key] || []);
    const t = S.telemetry[key]; if (typeof t.temp_c === "number") { hist.push(t.temp_c); if (hist.length > 60) hist.shift(); }
    if (hist.length < 2) return;
    const g = cv.getContext("2d"), w = cv.width, h = cv.height;
    g.clearRect(0, 0, w, h);
    const lo = Math.min(...hist, 16), hi = Math.max(...hist, 26), sp = Math.max(hi - lo, 1);
    const col = level === "critical" ? BANDS.RED : level === "warn" ? BANDS.YELLOW : BANDS.GREEN;
    g.strokeStyle = col; g.lineWidth = 1.5; g.beginPath();
    hist.forEach((v, i) => { const x = i / (hist.length - 1) * w, y = h - (v - lo) / sp * (h - 6) - 3; i ? g.lineTo(x, y) : g.moveTo(x, y); });
    g.stroke();
  }

  // ── topology ────────────────────────────────────────────────────────────
  function renderTopo() {
    const svg = $("#topo"); if (!svg) return;
    const NS = "http://www.w3.org/2000/svg";
    const nodes = [
      { id: "router", x: 330, y: 20, w: 150, h: 36, t: "ROUTER", s: "uplink · port 1" },
      { id: "switch", x: 300, y: 92, w: 160, h: 36, t: "8-PORT SWITCH", s: "production LAN" },
      { id: "sentinel", x: 40, y: 190, w: 180, h: 50, t: "PI 3 · SENTINEL", s: ".2 · detect+log" },
      { id: "core", x: 290, y: 190, w: 180, h: 50, t: "PI 4 · CORE", s: ".1 · engine" },
      { id: "herald", x: 540, y: 190, w: 180, h: 50, t: "PI 3 · HERALD", s: ".3 · smtp" },
      { id: "indicator", x: 290, y: 300, w: 180, h: 44, t: "ESP32-C3", s: "oled · neopixel" },
      { id: "rig", x: 540, y: 300, w: 180, h: 44, t: "ESP32-WROOM", s: "room rig" },
    ];
    // rooms along the bottom from telemetry
    const rks = Object.keys(S.telemetry).sort().slice(0, 4);
    rks.forEach((k, i) => nodes.push({ id: "room:" + k, x: 30 + i * 180, y: 392, w: 160, h: 50, t: (S.telemetry[k].room || k).toUpperCase(), s: (S.telemetry[k].temp_c != null ? S.telemetry[k].temp_c.toFixed(1) + "°C" : ""), room: k }));
    const edges = [
      ["router", "switch"], ["switch", "sentinel"], ["switch", "core"], ["switch", "herald"],
      ["core", "indicator", "usb"],
    ];
    rks.forEach((k) => edges.push(["rig", "room:" + k, "wifi"]));
    rks.forEach((k) => edges.push(["core", "room:" + k, "wifi"]));
    const by = Object.fromEntries(nodes.map((n) => [n.id, n]));
    const cx = (n) => n.x + n.w / 2, cy = (n) => n.y + n.h / 2;

    let h = `<rect class="t-zone" x="12" y="150" width="736" height="120" rx="8"/><text class="t-zl" x="20" y="166">PRODUCTION · 192.168.100.0/24</text>`;
    for (const [a, b, kind] of edges) {
      const n1 = by[a], n2 = by[b]; if (!n1 || !n2) continue;
      const hot = (kind === "wifi" && a === "core") && topoHot(b);
      h += `<path class="t-edge ${kind === "wifi" ? "wifi" : ""} ${hot ? "hot" : ""}" d="M${cx(n1)} ${n1.y + n1.h} C ${cx(n1)} ${(n1.y + n1.h + n2.y) / 2}, ${cx(n2)} ${(n1.y + n1.h + n2.y) / 2}, ${cx(n2)} ${n2.y}"/>`;
    }
    for (const n of nodes) {
      const cls = nodeClass(n);
      const led = n.room ? "" : `<circle class="led" cx="${n.x + n.w - 12}" cy="${n.y + 12}" r="4" fill="${nodeLed(n.id)}"/>`;
      h += `<g class="t-node ${cls}"><rect x="${n.x}" y="${n.y}" width="${n.w}" height="${n.h}" rx="7"/>${led}<text class="tt" x="${n.x + 12}" y="${n.y + 21}">${esc(n.t)}</text><text class="ts" x="${n.x + 12}" y="${n.y + 36}">${esc(n.s)}</text></g>`;
    }
    svg.innerHTML = h;
  }
  function nodeClass(n) {
    if (n.room) { const lv = (S.devices[n.room] || {}).level; const off = (Date.now() / 1000 - (S.telemetry[n.room].rx || 0)) > 15; return off ? "off" : lv === "critical" ? "crit" : lv === "warn" ? "warn" : (S.incident && S.incident.device === n.room && S.incident.action ? "fix" : ""); }
    if (["core", "sentinel", "herald"].includes(n.id)) return isUp(n.id) ? "" : "off";
    if (n.id === "indicator" || n.id === "rig") return isUp(n.id) ? "" : "off";
    return "";
  }
  function nodeLed(id) { if (id === "core") return BANDS[S.band] || BANDS.BLUE; return isUp(id) ? BANDS.GREEN : "#444"; }
  function topoHot(b) { return S.incident && S.incident.action && ("room:" + S.incident.device) === b; }

  // ── events feed ─────────────────────────────────────────────────────────
  function pushEvent(e) { S.events.push(e); if (S.events.length > 250) S.events.shift(); renderEvents(); }
  function renderEvents() {
    const ul = $("#feed"); if (!ul) return;
    const f = S.filter;
    const match = (e) => f === "all" ? true
      : f === "detect" ? ["portscan", "arpsweep", "pingsweep", "flood", "newdevice", "anomaly", "integrity", "device-offline"].includes(e.kind)
      : f === "incident" ? ["alert", "incident", "action", "command"].includes(e.kind)
      : f === "mail" ? e.kind === "mail"
      : f === "system" ? ["node", "rig"].includes(e.kind) : true;
    const list = S.events.filter(match).slice(-120).reverse();
    $("#ev-count").textContent = S.events.length + " total";
    ul.innerHTML = "";
    for (const e of list) {
      const li = el("li", "s-" + (e.sev || "info") + " k-" + e.kind);
      li.innerHTML = `<span class="d"></span><span class="tm">${hms(e.ts)}</span><span class="tx">${esc(e.title)}<small>${esc(e.node || e.kind)}${e.src ? " · " + esc(e.src) : ""}</small></span>`;
      ul.appendChild(li);
    }
    if (!list.length) ul.innerHTML = `<li style="grid-template-columns:1fr"><span class="tx dim" style="font-style:italic">Nothing here yet.</span></li>`;
  }

  // ── fleet ───────────────────────────────────────────────────────────────
  function renderFleet() {
    const box = $("#fleet"); if (!box) return;
    const ids = ["core", "sentinel", "herald", "verifier", "indicator", "rig"];
    let up = 0;
    box.innerHTML = "";
    for (const id of ids) {
      const h = S.nodes[id], on = isUp(id); if (on) up++;
      const [name, role] = NODE_META[id];
      const n = el("div", "node " + (on ? "on" : "off"));
      let detail = "";
      if (h) {
        if (id === "sentinel") detail = `usb <span class="${h.usb ? "ok" : "bad"}">${h.usb ? "mounted" : "missing"}</span> · ${h.logged_lines || 0} logged · ${h.pkts || 0} pkt`;
        else if (id === "herald") detail = `smtp <span class="${h.configured ? "ok" : "bad"}">${h.configured ? "ready" : "unset"}</span>${h.last_ok === false ? ' · <span class="bad">last failed</span>' : h.last_ok ? ' · <span class="ok">last ok</span>' : ""}`;
        else if (id === "core") detail = `band ${h.band || "?"} · score ${h.score != null ? h.score : "?"}`;
        else if (id === "verifier") detail = `${h.polls || 0} checks · ${h.mismatches || 0} mismatch`;
        else if (id === "indicator") detail = `serial <span class="${h.link ? "ok" : "bad"}">${h.link ? "open" : "closed"}</span>`;
        else detail = h.role || "";
      } else detail = "no heartbeat";
      n.innerHTML = `<div class="nh"><i></i>${name}</div><div class="nr">${role}</div><div class="nk">${detail}</div>`;
      box.appendChild(n);
    }
    $("#fleet-sub").textContent = up + "/" + ids.length + " up";
  }

  // ── footer / clock ──────────────────────────────────────────────────────
  function tick() {
    const d = new Date(Date.now() + S.serverSkew);
    $("#clock").textContent = d.toLocaleTimeString("en-GB", { hour12: false });
    // live countdown without waiting for the next state frame
    if (S.incident && S.incident.state === "open") {
      const cd = $("#cd"); if (cd) { const left = Math.max(0, (S.incident.deadline - (Date.now() + S.serverSkew) / 1000)); cd.textContent = Math.ceil(left); }
    }
    S.rate = S.msgCount; $("#f-rate").textContent = S.rate; S.msgCount = 0;
    $("#f-events").textContent = S.events.length;
    $("#f-open").textContent = S.incident && S.incident.state !== "resolved" ? 1 : 0;
  }
  function raf() { drawGraph(); drawOled(); drawNeo(); requestAnimationFrame(raf); }

  // ── misc ────────────────────────────────────────────────────────────────
  function esc(s) { return String(s == null ? "" : s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c])); }
  function hms(ts) { return new Date((ts || 0) * 1000).toLocaleTimeString("en-GB", { hour12: false }); }
  function toast(t) { const box = $("#toast"); const d = el("div", null, t); box.appendChild(d); setTimeout(() => d.remove(), 5000); }

  // chips
  $("#chips")?.addEventListener("click", (e) => {
    const b = e.target.closest("button"); if (!b) return;
    S.filter = b.dataset.f;
    for (const x of $("#chips").children) x.classList.toggle("on", x === b);
    renderEvents();
  });
  $("#c-mail")?.addEventListener("click", () => { send({ op: "mail-test" }); toast("Test e-mail requested from Herald"); });
  $("#c-spike")?.addEventListener("click", () => { send({ op: "rig", scenario: "ac-spike", device: "room1-ac" }); toast("Told the rig to spike Room 1 AC"); });
  $("#c-reset")?.addEventListener("click", () => { send({ op: "rig", scenario: "reset" }); toast("Told the rig to reset"); });
  $("#lock-btn")?.addEventListener("click", async () => { await window.ReWatchAuth.logout(); location.reload(); });

  window.ReWatch = {
    start() {
      if (ws) return;
      connect();
      setInterval(tick, 500); tick();
      requestAnimationFrame(raf);
      // incident + rooms repaint each second so countdowns/sparks stay live
      setInterval(() => { renderIncident(); renderRooms(); }, 1000);
    },
  };
})();
