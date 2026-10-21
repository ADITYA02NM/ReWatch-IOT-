#!/usr/bin/env python3
"""Build the demo front-end from the shared production front-end.

The demo serves risk.js / topology.js / devices.js / devices.css straight from
pi4-core/web/assets, but it keeps its own index.html and live.js because the
simulation adds replay, the synthetic Black Hat feed and a 20 second ACK
deadline. This script regenerates those two files so the two front-ends cannot
drift apart silently.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROD_ASSETS = ROOT / "pi4-core" / "web" / "assets"
DEMO_WEB = ROOT / "demo" / "web"


def apply(text: str, old: str, new: str, count: int = 1) -> str:
    if text.count(old) != count:
        raise SystemExit(f"pattern not found exactly {count}x: {old[:70]!r}")
    return text.replace(old, new)


# ── live.js ────────────────────────────────────────────────────────────────
live = (PROD_ASSETS / "live.js").read_text(encoding="utf-8")

live = apply(live,
    "    devices: {}, telemetry: {}, verify: {}, nodes: {}, history: [], events: [], mqtt: false,",
    "    devices: {}, telemetry: {}, verify: {}, nodes: {}, history: [], events: [], mqtt: false, simulation: false,")

live = apply(live,
    "  let ws = null, eventPage = 0;",
    """  let ws = null, eventPage = 0;

  function briefingState(on) {
    const button = $("#btn-blackhat");
    if (button) { button.setAttribute("aria-pressed", String(!!on)); button.textContent = "Black Hat feed: " + (on ? "ON" : "OFF"); }
  }""")

live = apply(live,
    '      else if (m.t === "mqtt") { S.mqtt = m.ok; }',
    """      else if (m.t === "mqtt") { S.mqtt = m.ok; }
      else if (m.t === "demo") briefingState(m.briefing);""")

live = apply(live,
    '    S.mqtt = m.mqtt; if (m.version) $("#f-ver").textContent = "ReWatch IoT · v" + m.version;',
    """    S.mqtt = m.mqtt; S.simulation = m.simulation === true;
    if ($("#mail-status")) $("#mail-status").textContent = (m.mail_status || "Preview only") + " · System summaries every 5 minutes.";
    if (m.version) $("#f-ver").textContent = "ReWatch IoT · SIMULATION · " + m.version;
    if (m.briefing != null) briefingState(m.briefing);""")

live = apply(live, "|| 120;", "|| 20;")
live = apply(live,
    "a RED crossing opens one here with a countdown.",
    "In this simulation, RED opens an incident with a 20-second countdown. Production defaults to 120 seconds.")

live = apply(live,
    '    const fresh = S.conn === "live" && S.mqtt;',
    '    const fresh = S.conn === "live" && (S.mqtt || S.simulation);')

live = apply(live,
    "  function pushEvent(e) { S.events.push(e); if (S.events.length > 250) S.events.shift(); renderEvents(); }",
    """  function pushEvent(e) {
    S.events.push(e); if (S.events.length > 250) S.events.shift(); renderEvents();
    if (e.kind === "mail" && $("#mail-status")) $("#mail-status").textContent = e.title + " · Summaries every 5 minutes.";
  }""")

live = apply(live,
    '  $("#btn-mail")?.addEventListener("click", () => { send({ op: "mail-test" }); toast("Test e-mail requested from Herald"); });',
    """  $("#btn-mail")?.addEventListener("click", () => { send({ op: "mail-test" }); toast("Mail preview/test requested — the result lands in the alert feed"); });
  $("#btn-replay")?.addEventListener("click", () => { send({ op: "replay" }); toast("Replay restarted: discovery 20 s, spike 30 s"); });
  $("#btn-blackhat")?.addEventListener("click", () => { send({ op: "briefing" }); toast("Toggled the synthetic detection feed — no network attacks run"); });
  $("#btn-firmware")?.addEventListener("click", () => { send({ op: "firmware-demo" }); toast("Simulated reported firmware changed — not attestation"); });""")

live = apply(live,
    '    toast(busy ? "Room 1 setpoint restored" : "AC spike commanded on Room 1");',
    '    toast(busy ? "Simulated Room 1 setpoint restored" : "Simulated AC spike started on Room 1");')

(DEMO_WEB / "assets" / "live.js").write_text(live, encoding="utf-8")

# ── index.html ─────────────────────────────────────────────────────────────
index = (ROOT / "pi4-core" / "web" / "index.html").read_text(encoding="utf-8")

index = apply(index,
    "<span>Owner-only passkey</span><span>Zero cloud</span><span>2 × Pi 3 · Pi 4 · 2 × ESP32</span><span>Real hardware alerts</span>",
    "<span>Local recording demo</span><span>Synthetic IoT evidence</span><span>2 × Pi 3 · Pi 4 · 2 × ESP32 design</span><span>Nothing leaves this machine</span>")

index = apply(index,
    '        <a class="btn" href="reports.html" title="Open the 5-hour evidence report">▤ Evidence · 5h</a>\n      </div>',
    """        <a class="btn" href="reports.html" title="Open the 5-hour evidence report">▤ Evidence · 5h</a>
        <button class="btn" type="button" id="btn-replay" title="Restart the scripted sequence — the scene only">⟲ Replay sequence</button>
        <button class="btn" type="button" id="btn-blackhat" aria-pressed="false" title="Toggle the synthetic detection feed">Black Hat feed: OFF</button>
        <button class="btn" type="button" id="btn-firmware" title="Simulate a device reporting a new firmware version">⇅ Firmware drill</button>
      </div>""")

index = apply(index,
    '      <p id="ctl-note" role="status">Buttons act on the live system; nothing here deletes stored evidence.</p>',
    """      <p id="mail-status" role="status">E-mail preview only · system summaries every 5 min.</p>
      <p id="c-note">SIMULATION · discovery 20 s → spike 30 s → ACK 20 s. Refresh reconnects; Replay restarts the scene.</p>
      <p id="ctl-note" role="status">Buttons act on the running simulation; nothing here deletes stored evidence.</p>""")

(DEMO_WEB / "index.html").write_text(index, encoding="utf-8")
print("demo front-end regenerated")
