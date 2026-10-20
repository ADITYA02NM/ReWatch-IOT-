/* Section 01 — Risk: speedometer gauge + hoverable score history.
   Semi-circular (180°) speedometer on the left, the big score on the right;
   hovering the history graph reveals the score and the alert active then. */
(() => {
  "use strict";
  const $ = (s) => document.querySelector(s);
  const BANDS = { GREEN: "#34d27b", BLUE: "#4c8dff", YELLOW: "#f2c230", RED: "#ff4a3d", PURPLE: "#b45cff" };
  const clamp = (v, a, b) => Math.max(a, Math.min(b, v));
  const START = 270, SWEEP = 180;          // semicircle: left → top → right
  let S = null, arcs = {}, needle = null, tip = null, hover = null, built = false;

  function arcPath(r, from, to) {
    const p = (deg) => {
      const a = (deg - 90) * Math.PI / 180;
      return [100 + r * Math.cos(a), 100 + r * Math.sin(a)];
    };
    const [x1, y1] = p(from), [x2, y2] = p(to);
    return `M ${x1.toFixed(2)} ${y1.toFixed(2)} A ${r} ${r} 0 ${to - from > 180 ? 1 : 0} 1 ${x2.toFixed(2)} ${y2.toFixed(2)}`;
  }

  function build() {
    const host = $("#gauge");
    if (!host || built) return;
    built = true;
    const r = 76, w = 11;
    const ticks = [];
    for (const [val, label] of [[0, "0"], [30, "30"], [70, "70"], [100, "100"]]) {
      const a = (START + (val / 100) * SWEEP) * Math.PI / 180;
      const r1 = r - w / 2 - 1, r2 = r + w / 2 + 1;
      const col = val === 30 ? BANDS.YELLOW : val === 70 ? BANDS.RED : "rgba(255,255,255,.28)";
      ticks.push(`<line x1="${(100 + r1 * Math.cos(a)).toFixed(2)}" y1="${(100 + r1 * Math.sin(a)).toFixed(2)}" x2="${(100 + r2 * Math.cos(a)).toFixed(2)}" y2="${(100 + r2 * Math.sin(a)).toFixed(2)}" stroke="${col}" stroke-width="1.5"/>`);
      const lx = 100 + (r + 14) * Math.cos(a), ly = 100 + (r + 14) * Math.sin(a);
      ticks.push(`<text x="${lx.toFixed(2)}" y="${(ly + 3).toFixed(2)}" text-anchor="middle" class="g-tick">${label}</text>`);
    }
    host.innerHTML = `
      <svg viewBox="0 4 200 112" role="img" aria-label="Risk score dial">
        <line class="g-base" x1="${(100 - r).toFixed(1)}" y1="100" x2="${(100 + r).toFixed(1)}" y2="100"/>
        <path class="g-track" d="${arcPath(r, START, START + SWEEP)}" stroke-width="${w}" fill="none"/>
        <path class="g-zone" d="${arcPath(r, START + SWEEP * 0.3, START + SWEEP * 0.7)}" stroke="${BANDS.YELLOW}" stroke-width="${w}" fill="none" opacity=".16"/>
        <path class="g-zone" d="${arcPath(r, START + SWEEP * 0.7, START + SWEEP)}" stroke="${BANDS.RED}" stroke-width="${w}" fill="none" opacity=".18"/>
        <path class="g-arc" d="${arcPath(r, START, START + SWEEP)}" stroke-width="${w}" fill="none" stroke-linecap="round"/>
        <g class="g-ticks">${ticks.join("")}</g>
        <line class="g-needle" x1="100" y1="100" x2="100" y2="34" stroke-width="2.2" stroke-linecap="round"/>
        <circle class="g-hub" cx="100" cy="100" r="5"/>
      </svg>`;
    arcs = {
      value: host.querySelector(".g-arc"), needle: host.querySelector(".g-needle"),
      score: $("#score-num"), band: $("#band-big"),
    };
    tip = $("#graph-tip");
  }

  function draw() {
    if (!S) return;
    build();
    const score = clamp(Number(S.score) || 0, 0, 100);
    const p = score / 100;
    const color = BANDS[S.band] || BANDS.GREEN;
    const len = 2 * Math.PI * 76 * (SWEEP / 360);
    arcs.value.setAttribute("stroke", color);
    arcs.value.setAttribute("stroke-dasharray", `${(len * p).toFixed(1)} ${len}`);
    arcs.value.setAttribute("opacity", p > 0.005 ? "1" : "0");
    arcs.needle.setAttribute("transform", `rotate(${START + SWEEP * p} 100 100)`);
    arcs.needle.setAttribute("stroke", color);
    if (arcs.score) arcs.score.textContent = String(Math.round(score));
    if (arcs.band) { arcs.band.textContent = S.band || "—"; arcs.band.style.color = color; }
    drawGraph();
  }

  // ── history graph ────────────────────────────────────────────────────────
  function drawGraph() {
    const cv = $("#graph"); if (!cv || !S) return;
    const dpr = window.devicePixelRatio || 1, w = cv.clientWidth, h = cv.clientHeight;
    if (!w || !h) return;
    if (cv.width !== Math.round(w * dpr)) { cv.width = Math.round(w * dpr); cv.height = Math.round(h * dpr); }
    const g = cv.getContext("2d"); g.setTransform(dpr, 0, 0, dpr, 0, 0); g.clearRect(0, 0, w, h);
    // GREEN calm baseline, then the YELLOW/RED thresholds
    for (const [val, col] of [[0, BANDS.GREEN], [S.thresholds?.yellow ?? 30, BANDS.YELLOW],
                              [S.thresholds?.red ?? 70, BANDS.RED]]) {
      const y = h - (val / 100) * h - (val === 0 ? 1.5 : 0); g.strokeStyle = col + "44";
      g.setLineDash([3, 4]); g.beginPath(); g.moveTo(0, y); g.lineTo(w, y); g.stroke();
    }
    g.setLineDash([]);
    const hist = S.history || [];
    if (hist.length < 2) { $("#gleg").textContent = "collecting samples…"; return; }
    const t0 = hist[0][0], t1 = hist[hist.length - 1][0], span = Math.max(t1 - t0, 1);
    const X = (t) => (t - t0) / span * w, Y = (v) => h - (clamp(v, 0, 100) / 100) * h;
    g.beginPath(); g.moveTo(X(hist[0][0]), h);
    for (const p of hist) g.lineTo(X(p[0]), Y(p[1]));
    g.lineTo(X(t1), h); g.closePath();
    const grd = g.createLinearGradient(0, 0, 0, h); const ac = BANDS[S.band] || BANDS.GREEN;
    grd.addColorStop(0, ac + "55"); grd.addColorStop(1, ac + "05"); g.fillStyle = grd; g.fill();
    g.lineWidth = 1.8; g.lineJoin = "round";
    for (let i = 1; i < hist.length; i++) {
      g.strokeStyle = BANDS[hist[i][2]] || BANDS.GREEN; g.beginPath();
      g.moveTo(X(hist[i - 1][0]), Y(hist[i - 1][1])); g.lineTo(X(hist[i][0]), Y(hist[i][1])); g.stroke();
    }
    const last = hist[hist.length - 1]; g.fillStyle = BANDS[last[2]] || BANDS.GREEN;
    g.beginPath(); g.arc(X(last[0]), Y(last[1]), 3, 0, 7); g.fill();
    if (hover) {
      g.strokeStyle = "rgba(255,255,255,.35)"; g.lineWidth = 1;
      g.beginPath(); g.moveTo(hover.x, 0); g.lineTo(hover.x, h); g.stroke();
      g.fillStyle = BANDS[hover.band] || "#fff";
      g.beginPath(); g.arc(hover.x, hover.y, 4, 0, 7); g.fill();
    }
    $("#gleg").textContent = Math.round(span / 60) + " min · " + hist.length + " samples";
  }

  /* Nearest sample under the pointer, plus the alert that was active then. */
  function sampleAt(px) {
    const hist = S?.history || [];
    if (hist.length < 2) return null;
    const cv = $("#graph"); const w = cv.clientWidth;
    const t0 = hist[0][0], t1 = hist[hist.length - 1][0], span = Math.max(t1 - t0, 1);
    const t = t0 + (px / w) * span;
    let best = hist[0], bestD = Infinity;
    for (const p of hist) { const d = Math.abs(p[0] - t); if (d < bestD) { bestD = d; best = p; } }
    const events = (S.events || []).filter((e) => e.ts <= best[0] && best[0] - e.ts <= 180);
    const alert = events.length ? events[events.length - 1] : null;
    return { ts: best[0], score: best[1], band: best[2], alert };
  }

  function bindGraph() {
    const cv = $("#graph"); if (!cv) return;
    cv.addEventListener("mousemove", (event) => {
      if (!S) return;
      const rect = cv.getBoundingClientRect();
      const px = clamp(event.clientX - rect.left, 0, rect.width);
      const hit = sampleAt(px); if (!hit) return;
      const hist = S.history || [];
      const t0 = hist[0][0], t1 = hist[hist.length - 1][0], span = Math.max(t1 - t0, 1);
      const h = cv.clientHeight;
      hover = { x: (hit.ts - t0) / span * rect.width, y: h - (clamp(hit.score, 0, 100) / 100) * h, band: hit.band };
      if (tip) {
        const time = new Date(hit.ts * 1000).toLocaleTimeString("en-GB", { hour12: false });
        tip.hidden = false;
        tip.innerHTML = "";
        const head = document.createElement("b");
        head.textContent = time + " · score " + Math.round(hit.score) + " · " + hit.band;
        const body = document.createElement("span");
        body.textContent = hit.alert ? "alert then: " + hit.alert.title : "no alert in that window";
        tip.append(head, body);
        const left = clamp(hover.x, 4, Math.max(rect.width - 150, 4));
        tip.style.left = left + "px";
        tip.style.top = Math.max(hover.y - 46, 2) + "px";
      }
      drawGraph();
    });
    cv.addEventListener("mouseleave", () => { hover = null; if (tip) tip.hidden = true; drawGraph(); });
  }

  function bindGaugeTip() {
    const dial = document.querySelector(".risk-dial");
    const host = $("#gauge");
    if (!dial || !host) return;
    let el = $("#gauge-tip");
    if (!el) {
      el = document.createElement("div");
      el.id = "gauge-tip"; el.className = "graph-tip"; el.hidden = true;
      el.setAttribute("role", "status");
      dial.append(el);
    }
    host.addEventListener("mousemove", (event) => {
      if (!S) return;
      const recent = (S.events || []).slice(-1)[0];
      const score = Math.round(clamp(Number(S.score) || 0, 0, 100));
      el.hidden = false;
      el.textContent = "";
      const head = document.createElement("b");
      head.textContent = `score ${score} · ${S.band || "—"}`;
      const body = document.createElement("span");
      const stamp = recent ? new Date(recent.ts * 1000).toLocaleTimeString("en-GB", { hour12: false }) : null;
      body.textContent = recent
        ? `latest alert ${stamp}: ${recent.title}`
        : "no alert yet in this run";
      const cause = document.createElement("span");
      cause.textContent = " · " + (S.reason || "all quiet");
      el.append(head, body, cause);
      const rect = dial.getBoundingClientRect();
      el.style.left = clamp(event.clientX - rect.left - 40, 0, Math.max(rect.width - 170, 0)) + "px";
      el.style.top = (rect.height - 8) + "px";
    });
    host.addEventListener("mouseleave", () => { el.hidden = true; });
  }

  window.ReWatchRisk = {
    update(state) { S = state; draw(); },
    bind() { build(); bindGraph(); bindGaugeTip(); },
  };
})();
