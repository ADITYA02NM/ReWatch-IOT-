#!/usr/bin/env python3
"""ReWatch IoT — Black Hat demo server (single machine, no hardware, no broker).

This serves a demo dashboard and runs the production detector and threat engine
in-process. Traffic, devices and responses are simulated, not hardware evidence.

    python demo_server.py           # http://localhost:8080
    python demo_server.py --port 9000 --code 2026

Sign in with the passkey (works on localhost) or the access code printed at
start-up. Then:
  * Start/replay: discovery at 20 s, AC spike at 30 s, then RED and a 20 s
    acknowledgement window. No acknowledgement triggers a simulated reset.
  * A separate Black Hat feed injects synthetic detections, not real attacks.

No e-mail actually leaves the machine in demo mode (DEMO_SEND_MAIL=1 to really
send, using the same SMTP settings as the real Herald).
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import ipaddress
import math
import os
import random
import secrets
import sys
import time
from pathlib import Path
from urllib.parse import urlsplit

from aiohttp import WSMsgType, web

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
for module_path in (ROOT / "common", ROOT / "pi3-sentinel", ROOT / "pi4-core"):
    sys.path.insert(0, str(module_path))
import rewatch as rw            # noqa: E402
import engine as engmod         # noqa: E402
from detector import AnomalyDetector, ScanDetector, ScanConfig  # noqa: E402
from server.auth import SESSION_COOKIE, add_auth_routes  # noqa: E402
from server.auth_db import AuthDB  # noqa: E402
from server.app import Store  # noqa: E402
from server.devices import add_device_routes  # noqa: E402
from iot import DevicePolicy, FirmwareMonitor  # noqa: E402
from summary import ReportWindow  # noqa: E402

WEB = HERE / "web"
CSP = ("default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
       "img-src 'self' data:; font-src 'self'; connect-src 'self' ws: wss:; "
        "frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
PAGES = {"/": "index.html", "/index.html": "index.html", "/reports.html": "reports.html",
         "/debug.html": "debug.html", "/manual.html": "manual.html"}
ROOMS = {"room1-ac": "Room 1", "room2-ac": "Room 2", "room3-ac": "Room 3", "room4-ac": "Room 4"}
EXTRAS = {
    "entry-camera": {"kind": "camera", "room": "Entrance camera", "recording": True},
    "entry-door": {"kind": "door", "room": "Entrance door", "lock": True, "forced_open": False},
    "lobby-plug": {"kind": "plug", "room": "Lobby plug", "power": True, "power_w": 120},
    "lobby-light": {"kind": "light", "room": "Lobby light", "power": True, "brightness": 70},
    "lobby-fan": {"kind": "fan", "room": "Lobby fan", "power": True, "speed": 40},
    "safety-sensor": {"kind": "sensor", "room": "Safety sensor", "smoke": False, "leak": False},
}
DEMO_ACTIONS = {"camera": ["recording"], "door": ["lock"], "plug": ["power"],
                "light": ["power", "brightness"], "fan": ["power", "speed"], "sensor": []}
NODE_LABEL = {"core": "Pi 4 Core", "sentinel": "Pi 3 Sentinel", "herald": "Pi 3 Herald",
              "indicator": "ESP32-C3 indicator", "rig": "ESP32-WROOM rig", "verifier": "Pi 4 Wi-Fi verifier"}
SEV_OF_LEVEL = {"ok": "info", "warn": "medium", "critical": "critical"}


# ─────────────────────────────────────────────────────────────────────────────
# The simulated building + the real threat engine, wired through an internal bus
# ─────────────────────────────────────────────────────────────────────────────
class Sim:
    def __init__(self, app: web.Application, send_mail: bool) -> None:
        self.app = app
        self.send_mail = send_mail
        self.policy = DevicePolicy({
            **{k: {"kind": "ac", "enabled": True, "actions": ["setpoint"]} for k in ROOMS},
            **{k: {"kind": v["kind"], "enabled": True, "actions": DEMO_ACTIONS[v["kind"]]}
               for k, v in EXTRAS.items()},
        })
        self.eng = engmod.ThreatEngine(ack_timeout=rw.env_float("DEMO_ACK_TIMEOUT_S", 20),
                                       purple_hold=20, resolve_hold=4, device_policy=self.policy,
                                       network_enforcement=False)
        self.anom = AnomalyDetector(device_profiles=self.policy.devices)
        self.firmware = FirmwareMonitor(self.policy)
        self.extras = {k: {**v, "firmware": "demo-1.0"} for k, v in EXTRAS.items()}
        self.scan = ScanDetector(ScanConfig(cooldown_s=0))
        self.rooms = {k: {"temp": 20.0 + i * 0.4, "setpoint": 20.0, "target": 20.0, "room": v,
                          "spiked": False}
                      for i, (k, v) in enumerate(ROOMS.items())}
        self.nodes = {n: {"node": n, "online": True, "role": NODE_LABEL[n], "rx": time.time(),
                          "usb": True, "logged_lines": 0, "pkts": 0, "configured": True,
                          "last_ok": None, "band": "GREEN", "score": 0, "link": True}
                      for n in ("core", "sentinel", "herald", "verifier", "indicator", "rig")}
        self.telemetry: dict = {}
        self.verify: dict = {}
        self.history: list = []
        self.recent: list = []
        self.state: dict | None = {
            "band": "GREEN", "score": 0.0, "reason": "All quiet — nothing above noise.",
            "contrib": [], "incident": None, "thresholds": {"yellow": 30, "red": 70},
            "ts": time.time(),
        }
        self._briefing_overrides: dict[str, tuple[dict, float]] = {}
        self.briefing = False
        self.logged = 0
        self.pkts = 0
        self._auto_spiked = False
        self._last_sample = 0.0
        self.started_at: float | None = None
        self.discovered = False
        self.generation = 0

    def replay(self, now: float) -> None:
        """One shared building: an explicit replay resets every connected viewer.

        Score / events / graph / incident are cleared by __init__.
        IoT device inventory (telemetry, verify, discovered) is preserved so
        the connections map never goes blank during a replay.
        """
        saved_telemetry = dict(self.telemetry)
        saved_verify = dict(self.verify)
        saved_discovered = self.discovered
        generation = self.generation + 1
        self.__init__(self.app, self.send_mail)
        self.generation = generation
        self.started_at = now
        # Restore device inventory — discovery-gated loops will keep refreshing it.
        # Rooms reset to cold baseline (target/temp 20.0, power 'on') so rigBusy() is false
        for dev, r in self.rooms.items():
            if dev in saved_telemetry:
                saved_telemetry[dev] = {
                    **saved_telemetry[dev],
                    "temp_c": round(r["temp"], 1),
                    "setpoint": r["setpoint"],
                    "power": "on",
                }
        self.telemetry = saved_telemetry
        self.verify = saved_verify
        self.discovered = saved_discovered

    def apply_mail_result(self, result: dict) -> None:
        ok = result.get("ok") is True
        self.nodes["herald"]["last_ok"] = ok
        self.app["mail_status"] = "SMTP accepted" if ok else "SMTP failed — check local settings"
        subject = str(result.get("subject") or "").strip()
        suffix = f" · {subject}" if subject else ""
        self._emit({"kind": "mail", "sev": "info" if ok else "medium", "node": "herald",
                    "title": ("E-mail accepted by SMTP server (delivery not confirmed)" if ok
                              else "E-mail failed — check local SMTP configuration") + suffix})

    # internal bus: engine publishes here; we turn it into events + state
    def _detect(self, topic: str, payload: dict, now: float) -> None:
        self.eng.on_message(topic, payload, now)
        if "summary" in self.app:
            self.app["summary"].observe(topic, payload, now)

    def _drain_engine(self) -> None:
        out, self.eng.out = self.eng.out, []
        for topic, payload, retain in out:
            self._on_engine(topic, payload)

    def _on_engine(self, topic: str, d: dict) -> None:
        if "summary" in self.app:
            self.app["summary"].observe(topic, d, d.get("ts", time.time()))
        if topic == rw.topic("threat", "state"):
            self.state = d
            return
        if topic.startswith(rw.topic("alert")):
            self._emit({"kind": "alert", "sev": "critical", "incident": d.get("id"),
                        "title": f"RED incident — {d.get('title')}", "node": "core",
                        "device": d.get("device", ""), "src": d.get("src", "")})
            self._mail("alert", d)
        elif topic.startswith(rw.topic("incident")):
            if "store" in self.app:
                self.app["store"].upsert_incident(d)
            st = d.get("state")
            words = {"acked": f"Acknowledged by {d.get('acked_by') or 'operator'}",
                     "auto": "No response in time — PURPLE automation",
                     "resolved": "Incident resolved — back to normal"}
            if st in words:
                self._emit({"kind": "incident", "sev": {"acked": "medium", "auto": "high",
                            "resolved": "info"}[st], "title": f"{words[st]} · {d.get('title','')}",
                            "incident": d.get("id"), "node": "core"})
                if st in ("acked", "auto", "resolved"):
                    self._mail(st, d)
        elif topic.startswith(rw.topic("action")):
            self._emit({"kind": "action", "sev": "high", "incident": d.get("incident"),
                        "node": "core", "device": d.get("device", ""),
                        "title": ("Manual" if d.get("manual") else "Automatic")
                        + " response — " + d.get("summary", "")})
        elif topic.endswith("/cmd") and "/iot/" in topic:
            dev = topic.split("/")[2]
            r = self.rooms.get(dev)
            if r:
                r["setpoint"] = float(d.get("setpoint", 20)); r["target"] = r["setpoint"]
                r["spiked"] = False
            elif dev in self.extras:
                self.extras[dev][d["action"]] = d["value"]
            self._emit({"kind": "command", "sev": "info", "device": dev, "node": "core",
                        "title": f"SIMULATED command → {dev}: {d.get('action', 'setpoint')} = "
                                 f"{d.get('value', d.get('setpoint'))}"})

    def _emit(self, e: dict) -> None:
        e.setdefault("id", rw.new_id(e["kind"][:3]))
        e.setdefault("ts", time.time())
        e.setdefault("src", "")
        self.recent.append(e)
        if "store" in self.app:
            self.app["store"].add_event({"device": "", "node": "demo", **e})
        if len(self.recent) > 250:
            self.recent.pop(0)
        self.app["broadcast"]({"t": "event", "e": e})

    def _mail(self, kind: str, d: dict) -> None:
        if not self.send_mail:
            self.app["mail_status"] = "Preview only — delivery disabled"
            to = os.environ.get("ALERT_TO", "owner@example.com")
            subj = {"alert": "RED — " + d.get("title", ""), "acked": "Acknowledged",
                    "auto": "PURPLE — response requested", "resolved": "Resolved",
                    "summary": "5-minute system summary", "test": "Test message"}.get(kind, "")
            self._emit({"kind": "mail", "sev": "info", "node": "herald",
                        "title": f"E-mail preview for {to} — [ReWatch] {subj} (delivery disabled)"})
            return
        # SMTP runs on a worker thread, never on the simulation/WS event loop.
        try:
            self.app["mail_queue"].put_nowait((self.generation, kind, dict(d)))
            self.app["mail_status"] = "SMTP queued — awaiting result"
        except (KeyError, asyncio.QueueFull):
            self.apply_mail_result({"ok": False})

    def send_mail_sync(self, kind: str, d: dict) -> dict:
        """Reuse Herald's TLS transport and composer; credentials stay in env."""
        try:
            sys.path.insert(0, str(ROOT / "pi3-herald"))
            import mailer  # type: ignore
            h = mailer.Herald.__new__(mailer.Herald)
            h.host = os.environ.get("SMTP_HOST", "smtp.gmail.com")
            h.port = int(os.environ.get("SMTP_PORT", "587"))
            h.user = os.environ.get("SMTP_USER", ""); h.password = os.environ.get("SMTP_PASS", "")
            h.sender = os.environ.get("SMTP_FROM", h.user)
            h.to = [x.strip() for x in os.environ.get("ALERT_TO", "").split(",") if x.strip()]
            h.iface = os.environ.get("SMTP_IFACE", "")
            h.dash = os.environ.get("DASHBOARD_URL", "http://localhost:8080")
            h.sent = set(); h.last = {}
            h.bus = type("B", (), {"publish": lambda *a, **k: None})()
            h.send(kind, d)
            return dict(h.last)
        except (ImportError, ValueError, OSError):
            return {"ok": False}

    # operator + rig commands from the dashboard
    def ack(self, inc_id: str):
        self.eng.ack(inc_id, "owner (demo)", time.time()); self._drain_engine()

    def respond(self, inc_id: str):
        self.eng.respond(inc_id, time.time(), manual=True); self._drain_engine()

    def rig(self, scenario: str, device: str = "room1-ac"):
        if scenario == "reset":
            for k, r in self.rooms.items():
                r["setpoint"] = 20.0; r["target"] = 20.0; r["spiked"] = False
        elif scenario == "ac-spike":
            self.discovered = True
            self._auto_spiked = True
            r = self.rooms.get(device)
            if r:
                r["target"] = 35.0; r["spiked"] = True
            self._emit({"kind": "rig", "sev": "info", "node": "rig", "device": device,
                        "title": f"Test rig: AC spike {device}"})

    def toggle_briefing(self):
        self.briefing = not self.briefing
        self._emit({"kind": "rig", "sev": "info", "node": "rig",
                    "title": f"Briefing mode {'on' if self.briefing else 'off'}"})
        return self.briefing

    def firmware_demo(self):
        self.discovered = True
        tel = self.extras["entry-camera"]
        tel["firmware"] = "demo-2.0" if tel["firmware"] == "demo-1.0" else "demo-1.0"

    # one tick of the world
    def tick(self, now: float) -> None:
        if self.started_at is not None:
            elapsed = now - self.started_at
            self.discovered = self.discovered or elapsed >= 20
            if elapsed >= 30 and not self._auto_spiked and rw.env_bool("DEMO_AUTO_SPIKE", True):
                self.rig("ac-spike")
        # devices ease toward target + tiny noise; publish telemetry -> anomaly -> engine
        for dev, r in (self.rooms.items() if self.discovered else []):
            r["temp"] += (r["target"] - r["temp"]) * 0.18 + random.uniform(-0.05, 0.05)
            tel = {"device": dev, "room": r["room"], "kind": "ac",
                   "temp_c": round(r["temp"], 1), "setpoint": r["setpoint"],
                   "ip": "192.168.100.5", "firmware": "demo-rig-1.0",
                   "power": "fault" if r["spiked"] else "on"}
            self.telemetry[dev] = {**tel, "rx": now}
            self.eng.on_message(rw.topic("iot", dev, "telemetry"), tel, now)
            cond = self.anom.feed(tel, now)
            if cond:
                self._detect(rw.topic("detect", "anomaly", dev), cond, now)
                if cond.get("changed"):
                    self._emit({"kind": "anomaly", "sev": SEV_OF_LEVEL[cond["level"]],
                                "device": dev, "node": "sentinel",
                                "title": f"{r['room']}: {cond['reason']}"})
            # verifier agrees (it reads the same honest device); the chip just
            # reflects reachability. No integrity alarm — the AC anomaly is the
            # real driver, and a truthful device never trips a mismatch.
            ok = not (r["spiked"] and r["temp"] > 30)
            self.verify[dev] = {"device": dev, "ok": ok, "mqtt_temp": round(r["temp"], 1),
                                "wifi_temp": round(r["temp"], 1), "rx": now}
            self.eng.on_message(rw.topic("verify", dev), {**self.verify[dev], "alarm": False}, now)

        if self.briefing and random.random() < 0.14:
            self._random_event(now)

        for i, (dev, fields) in enumerate(self.extras.items() if self.discovered else []):
            tel = {**fields, "device": dev, "ip": f"192.168.100.{60+i}", "rx": now}
            cond = self.anom.feed(tel, now)
            if cond:
                self._detect(rw.topic("detect", "anomaly", dev), cond, now)
            if dev in self._briefing_overrides:
                override, exp = self._briefing_overrides[dev]
                if now < exp:
                    tel.update(override)
                else:
                    self._briefing_overrides.pop(dev, None)
            self.telemetry[dev] = tel
            self.eng.on_message(rw.topic("iot", dev, "telemetry"), tel, now)
        for tel in self.telemetry.values():
            for ev in self.firmware.feed(tel, now):
                self._detect(rw.topic("detect", ev["kind"]), ev, now)
                self._emit({**ev, "node": "sentinel"})

        # fleet heartbeats stay fresh
        self.pkts += random.randint(2, 9)
        self.logged += 1
        for n, h in self.nodes.items():
            h["rx"] = now
            if "summary" in self.app:
                self.app["summary"].observe(rw.topic("health", n), h, now)
        self.nodes["herald"]["configured"] = bool(
            self.send_mail and os.environ.get("SMTP_USER") and os.environ.get("SMTP_PASS")
            and os.environ.get("ALERT_TO"))
        self.nodes["sentinel"].update(pkts=self.pkts, logged_lines=self.logged)
        self.eng.on_message(rw.topic("health", "sentinel"), {"node": "sentinel", "online": True}, now)
        self.eng.on_message(rw.topic("health", "herald"), {"node": "herald", "online": True}, now)

        self.eng.tick(now)
        self.nodes["core"].update(band=self.eng.band, score=round(self.eng.score))
        self._drain_engine()

        # Ambient LAN chatter: the *published* score breathes gently so the
        # graph shows life while calm. Display-only — never feeds incidents
        # (eng.score stays untouched) and peaks far below YELLOW (30).
        if self.state is not None:
            base = self.state.get("score", 0) or 0
            wob = 2.5 + 2.0 * math.sin(now / 17.0) + 1.0 * math.sin(now / 6.3)
            self.state["score"] = round(base + max(0.0, min(6.5, wob)), 1)

        if "summary" in self.app:
            report = self.app["summary"].poll(now)
            if report:
                report["simulation"] = True
                self.app["last_summary"] = report
                self._emit({"kind": "summary", "sev": "info", "node": "herald", "ts": now,
                            "title": f"SIMULATION · 5-minute summary: {report['band']}, "
                                     f"peak {report['peak']:.0f}, {len(self.telemetry)} devices"})
                self._mail("summary", report)

        if self.state and now - self._last_sample >= 1.0:
            self._last_sample = now
            self.history.append([now, self.state.get("score", 0), self.state.get("band")])
            if "store" in self.app:
                self.app["store"].add_sample(now, self.state.get("score", 0), self.state.get("band"))
            if len(self.history) > 600:
                self.history.pop(0)

    def _random_event(self, now: float):
        _ip = lambda: f"192.168.100.{random.randint(20, 250)}"  # noqa: E731
        _room = lambda: random.choice(list(ROOMS.values()))  # noqa: E731
        # Network scan / discovery detections.
        # All non-anomaly topics are counted by summary.ReportWindow.observe().
        network_pool = [
            ("portscan",  "critical", f"Aggressive TCP port scan from {_ip()} — {random.randint(500,5000)} ports probed"),
            ("portscan",  "high",     f"TCP port scan from {_ip()} — {random.randint(40,499)} ports"),
            ("arpsweep",  "high",     f"ARP sweep from {_ip()} — full subnet enumeration"),
            ("arpsweep",  "medium",   f"Host-discovery ARP sweep from {_ip()}"),
            ("pingsweep", "high",     f"ICMP sweep from {_ip()} — {random.randint(20,254)} hosts"),
            ("pingsweep", "medium",   f"Ping sweep from {_ip()}"),
            ("newdevice", "medium",   f"New device on LAN — {_mac()} ({_ip()})"),
            ("newdevice", "low",      f"Unregistered MAC {_mac()} joined 192.168.100.0/24"),
            ("flood",     "critical", f"UDP flood from {_ip()} — {random.randint(10,100)} kpps"),
            ("slow-scan", "medium",   f"Slow stealth scan from {_ip()} — evading rate limits"),
        ]
        # IoT-device alerts.
        # detect_kind is the engine/summary topic (integrity or device-offline — counted, not filtered).
        # display_kind is the emit kind shown in the UI.
        # Tuple: (detect_kind, display_kind, sev, device, title)
        iot_pool = [
            # Camera events
            ("integrity",     "anomaly", "critical", "entry-camera", "Camera motion detected — unscheduled access corridor"),
            ("integrity",     "anomaly", "high",     "entry-camera", "Camera recording gap — 47 s of missing footage"),
            ("integrity",     "anomaly", "medium",   "entry-camera", "Camera stream jitter — possible network interference"),
            ("device-offline","anomaly", "low",      "entry-camera", "Camera rebooted — firmware watchdog triggered"),
            # Door events
            ("integrity",     "anomaly", "critical", "entry-door",   "Forced-open alarm — entry door breached without auth"),
            ("integrity",     "anomaly", "high",     "entry-door",   "Door held open > 30 s — tailgating risk"),
            ("integrity",     "anomaly", "medium",   "entry-door",   "Door unlock command from unrecognised source"),
            ("device-offline","anomaly", "low",      "entry-door",   "Door sensor battery low — replacement recommended"),
            # Plug events
            ("integrity",     "anomaly", "critical", "lobby-plug",   "Plug power spike — 2.4 kW surge (rated 1.5 kW)"),
            ("integrity",     "anomaly", "high",     "lobby-plug",   "Lobby plug on outside scheduled hours"),
            ("integrity",     "anomaly", "medium",   "lobby-plug",   "Plug power draw anomaly — 40 % above baseline"),
            ("device-offline","anomaly", "low",      "lobby-plug",   "Plug RSSI degraded — possible obstruction"),
            # Light events
            ("integrity",     "anomaly", "high",     "lobby-light",  "Lights on in unoccupied zone (PIR negative)"),
            ("integrity",     "anomaly", "medium",   "lobby-light",  "Light brightness command rejected — controller unresponsive"),
            ("device-offline","anomaly", "low",      "lobby-light",  "Light flicker — driver undervoltage"),
            # Fan events
            ("integrity",     "anomaly", "high",     "lobby-fan",    "Fan speed command override — physical interlock suspected"),
            ("integrity",     "anomaly", "medium",   "lobby-fan",    "Fan running at 100 % — thermal event possible"),
            ("device-offline","anomaly", "low",      "lobby-fan",    "Fan speed oscillating — bearing wear indicator"),
            # Sensor events
            ("integrity",     "anomaly", "critical", "safety-sensor", "SMOKE DETECTED — safety sensor triggered"),
            ("integrity",     "anomaly", "critical", "safety-sensor", "WATER LEAK — safety sensor triggered"),
            ("device-offline","anomaly", "high",     "safety-sensor", "Sensor offline > 5 min — loss of safety coverage"),
            ("integrity",     "anomaly", "medium",   "safety-sensor", "Sensor self-test failed — calibration required"),
            # AC / room events (no device key)
            ("integrity",     "anomaly", "high",     None, f"{_room()} AC setpoint changed remotely without operator session"),
            ("integrity",     "anomaly", "medium",   None, f"{_room()} temperature deviation > 4 \u00b0C from setpoint"),
            ("integrity",     "anomaly", "medium",   None, f"{_room()} AC unresponsive to last three commands"),
            ("device-offline","anomaly", "low",      None, f"{_room()} AC filter maintenance alert"),
        ]
        # Pick exactly ONE detection event — summary counts one per _random_event call.
        if random.random() < 0.45:
            kind, sev, title = random.choice(network_pool)
            src = _ip()
            ev = rw.make_event(kind, sev, title, src=src)
            self._detect(rw.topic("detect", kind), ev, now)
            self._emit({"kind": kind, "sev": sev, "title": title, "node": "sentinel", "src": src})
        else:
            detect_kind, display_kind, sev, device, title = random.choice(iot_pool)
            base_ev = {"kind": display_kind, "sev": sev, "node": "sentinel", "title": title}
            if device:
                base_ev["device"] = device
                if device == "lobby-plug":
                    self._briefing_overrides[device] = ({"power_w": random.randint(2200, 2600)}, now + 4.0)
                elif device == "entry-door":
                    self._briefing_overrides[device] = ({"forced_open": True}, now + 5.0)
                elif device == "safety-sensor":
                    key = "smoke" if "SMOKE" in title else "leak"
                    self._briefing_overrides[device] = ({key: True}, now + 5.0)
                elif device == "lobby-fan":
                    self._briefing_overrides[device] = ({"speed": 100}, now + 4.5)
                elif device == "lobby-light":
                    val = 100 if "Lights on" in title else 15
                    self._briefing_overrides[device] = ({"brightness": val}, now + 4.0)
                elif device == "entry-camera":
                    if "gap" in title or "rebooted" in title:
                        self._briefing_overrides[device] = ({"recording": False}, now + 4.5)
            else:
                for dev, label in ROOMS.items():
                    if label in title:
                        base_ev["device"] = dev
                        r = self.rooms.get(dev)
                        if r and not r.get("spiked"):
                            r["temp"] = min(32.0, r["temp"] + random.uniform(2.5, 4.0))
                        break
            detect_ev = rw.make_event(detect_kind, sev, title, device=base_ev.get("device", ""))
            self._detect(rw.topic("detect", detect_kind), detect_ev, now)
            self._emit(base_ev)

    def snapshot(self) -> dict:
        now = time.time()
        return {"state": self.state, "nodes": self.nodes, "telemetry": self.telemetry,
                "verify": self.verify, "history": self.history[-200:],
                 "events": self.recent[-200:], "mqtt": False, "simulation": True,
                 "version": "demo", "briefing": self.briefing,
                  "demo_elapsed": max(0, now - self.started_at) if self.started_at else 0,
                 "mail_status": self.app.get("mail_status", "Preview only — delivery disabled"),
                 "last_summary": self.app.get("last_summary"),
                "server_ts": now}


def _mac():
    return ":".join(f"{random.randint(0,255):02x}" for _ in range(6))


# ─────────────────────────────────────────────────────────────────────────────
# HTTP / WS
# ─────────────────────────────────────────────────────────────────────────────
@web.middleware
async def headers(request, handler):
    origin = request.headers.get("Origin")
    if origin and origin not in request.app["auth_origins"]:
        raise web.HTTPForbidden(text="Origin not allowed")
    if request.method == "POST":
        try:
            body = await request.json()
        except (ValueError, UnicodeDecodeError):
            raise web.HTTPBadRequest(text="JSON object required") from None
        if not isinstance(body, dict):
            raise web.HTTPBadRequest(text="JSON object required")
    resp = await handler(request)
    resp.headers.setdefault("Content-Security-Policy", CSP)
    resp.headers.setdefault("X-Content-Type-Options", "nosniff")
    return resp


def session_ok(request) -> bool:
    sid = request.cookies.get(SESSION_COOKIE)
    return bool(sid and request.app["auth_db"].validate_session(sid))


async def page(request):
    resp = web.FileResponse(WEB / PAGES[request.path])
    resp.headers["Cache-Control"] = "no-store"
    return resp


async def asset(request):
    tail = request.match_info["tail"]
    if tail in ("devices.js", "devices.css", "risk.js", "topology.js"):
        return web.FileResponse(ROOT / "pi4-core" / "web" / "assets" / tail)
    target = (WEB / "assets" / tail).resolve()
    if (WEB / "assets").resolve() not in target.parents or not target.is_file():
        raise web.HTTPNotFound()
    return web.FileResponse(target)


async def healthz(request):
    return web.json_response({"ok": True, "mqtt": False, "simulation": True, "version": "demo",
                              "ws_clients": len(request.app["clients"])})


async def demo_options(request):
    return web.json_response({"passkey_preview": request.app["passkey_preview"],
                              "simulation": True})


def require_preview(request):
    if not request.app["passkey_preview"]:
        raise web.HTTPNotFound()
    try:
        local = ipaddress.ip_address(request.remote or "").is_loopback
    except ValueError:
        local = False
    hosts = {urlsplit(origin).netloc for origin in request.app["auth_origins"]}
    if not local or request.host not in hosts:
        raise web.HTTPForbidden(text="Preview is local-only")


async def preview_begin(request):
    require_preview(request)
    # Cosmetic browser ceremony: no result is ever described as verified.
    return web.json_response({"challenge": secrets.token_urlsafe(32), "rpId": "localhost",
                              "timeout": 60000, "userVerification": "required",
                              "allowCredentials": []})


async def preview_complete(request):
    require_preview(request)
    db = request.app["auth_db"]
    sid = db.create_session("demo-preview", ip=request.remote, ttl=3600,
                            enforce_credential_fkey=False)
    db.audit("demo_preview_unlock_unverified", ip=request.remote)
    response = web.json_response({"ok": True, "mode": "demo-preview", "verified": False})
    response.set_cookie(SESSION_COOKIE, sid, httponly=True, samesite="Strict", max_age=3600)
    return response


async def api_state(request):
    if not session_ok(request):
        raise web.HTTPUnauthorized(text="sign in first")
    return web.json_response(request.app["sim"].snapshot(), dumps=lambda o: json.dumps(o, default=str))


async def api_report(request):
    if not session_ok(request):
        raise web.HTTPUnauthorized(text="sign in first")
    sim: Sim = request.app["sim"]
    try:
        hours = max(0.25, min(48.0, float(request.query.get("hours", "5"))))
    except ValueError:
        hours = 5.0
    now = time.time(); since = now - hours * 3600
    store = request.app["store"]
    events = store.events(since)
    samples = store.samples(since)
    band_time: dict = {}
    for (t0, _, b), (t1, _, _) in zip(samples, samples[1:]):
        band_time[b] = band_time.get(b, 0) + min(t1 - t0, 5)
    counts: dict = {}; sev: dict = {}
    for e in events:
        counts[e["kind"]] = counts.get(e["kind"], 0) + 1
        sev[e["sev"]] = sev.get(e["sev"], 0) + 1
    inc = store.incidents(since)
    return web.json_response({"from": since, "to": now, "hours": hours,
                              "events": sorted(events, key=lambda e: e["ts"]), "incidents": inc,
                              "counts": counts, "sev_counts": sev, "band_time": band_time,
                              "series": [[h[0], h[1], h[2]] for h in samples],
                              "peak": max((s[1] for s in samples), default=0), "nodes": sim.nodes,
                              "simulation": True, "source": "persisted simulated evidence"})


async def ws_handler(request):
    if not session_ok(request):
        raise web.HTTPUnauthorized(text="sign in first")
    sim: Sim = request.app["sim"]
    if sim.started_at is None:
        sim.started_at = time.time()
    ws = web.WebSocketResponse(heartbeat=20, max_msg_size=16384)
    await ws.prepare(request)
    request.app["clients"].add(ws)
    if request.query.get("replay") == "1":
        sim.replay(time.time())
        request.app["broadcast"]({"t": "hello", **sim.snapshot()})
    else:
        await ws.send_str(json.dumps({"t": "hello", **sim.snapshot()}, default=str))
    try:
        async for msg in ws:
            if msg.type != WSMsgType.TEXT:
                continue
            try:
                m = json.loads(msg.data)
            except json.JSONDecodeError:
                continue
            if not isinstance(m, dict):
                continue
            op = m.get("op")
            if op == "ping":
                await ws.send_str(json.dumps({"t": "pong", "c": m.get("c"), "s": time.time()}))
            elif op == "ack":
                sim.ack(str(m.get("id", "")))
            elif op == "respond":
                sim.respond(str(m.get("id", "")))
            elif op == "rig":
                sim.rig(str(m.get("scenario", "")), str(m.get("device") or "room1-ac"))
            elif op == "mail-test":
                sim._mail("test", {"id": "test", "title": "Test e-mail"})
            elif op == "briefing":
                sim.toggle_briefing()
                request.app["broadcast"]({"t": "demo", "briefing": sim.briefing})
            elif op == "firmware-demo":
                sim.firmware_demo()
            elif op == "replay":
                sim.replay(time.time())
                request.app["broadcast"]({"t": "hello", **sim.snapshot()})
    except asyncio.CancelledError:
        pass  # shutdown: leave quietly instead of logging a handler failure
    finally:
        request.app["clients"].discard(ws)
    return ws


async def sim_loop(app):
    sim: Sim = app["sim"]
    while True:
        sim.tick(time.time())
        state = {"t": "bus", "topic": rw.topic("threat", "state"), "d": sim.state}
        app["broadcast"](state)
        # also push nodes/telemetry/verify so panels stay live
        for n, h in sim.nodes.items():
            app["broadcast"]({"t": "bus", "topic": rw.topic("health", n), "d": h})
        for dev, tel in sim.telemetry.items():
            app["broadcast"]({"t": "bus", "topic": rw.topic("iot", dev, "telemetry"), "d": tel})
            app["broadcast"]({"t": "bus", "topic": rw.topic("verify", dev), "d": sim.verify.get(dev, {})})
        await asyncio.sleep(0.5)


def broadcaster(app):
    async def _send(ws, data):
        try:
            await ws.send_str(data)
        except (ConnectionError, RuntimeError):
            app["clients"].discard(ws)

    def _b(frame):
        data = json.dumps(frame, default=str)
        for ws in list(app["clients"]):
            if ws.closed:
                app["clients"].discard(ws)
                continue
            asyncio.create_task(_send(ws, data))
    return _b


async def on_start(app):
    app["sim_task"] = asyncio.create_task(sim_loop(app))
    app["mail_task"] = asyncio.create_task(mail_loop(app))


async def mail_loop(app):
    while True:
        generation, kind, data = await app["mail_queue"].get()
        sim = app["sim"]
        if generation != sim.generation:
            continue
        try:
            result = await asyncio.to_thread(sim.send_mail_sync, kind, data)
        except Exception:
            result = {"ok": False}
        if generation == sim.generation:
            sim.apply_mail_result(result)


async def on_stop(app):
    for ws in list(app["clients"]):
        await ws.close(code=1001, message=b"Server shutting down")
    for name in ("sim_task", "mail_task"):
        app[name].cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await app[name]
    app["store"].db.close()


def create_app(port: int = 8080, code: str = "rewatch", auth_path: Path | None = None):
    app = web.Application(middlewares=[headers], client_max_size=65536)
    app["clients"] = set()
    app["mail_queue"] = asyncio.Queue(maxsize=20)
    app["broadcast"] = broadcaster(app)
    app["auth_db"] = AuthDB(auth_path or HERE / "_demo_auth.db")
    evidence = auth_path.with_name("demo-evidence.db") if auth_path else HERE / "_demo_evidence.db"
    app["store"] = Store(evidence)
    app["summary"] = ReportWindow()
    app["auth_rp_id"] = os.environ.get("REWATCH_RP_ID", "localhost")
    app["auth_rp_name"] = "ReWatch IoT (demo)"
    app["auth_origins"] = [f"http://localhost:{port}", f"http://127.0.0.1:{port}"]
    app["auth_secure_cookies"] = False
    app["demo_code"] = code
    app["passkey_preview"] = rw.env_bool("DEMO_PASSKEY_PREVIEW", False)
    app["sim"] = Sim(app, send_mail=rw.env_bool("DEMO_SEND_MAIL", False))
    add_auth_routes(app)

    async def publish_command(topic, data):
        app["sim"]._on_engine(topic, data)
        return True

    add_device_routes(app, app["sim"].policy, lambda: app["sim"].telemetry,
                      publish_command, simulation=True)
    for p in PAGES:
        app.router.add_get(p, page)
    app.router.add_get("/assets/{tail:.+}", asset)
    app.router.add_get("/healthz", healthz)
    app.router.add_get("/api/demo-options", demo_options)
    app.router.add_post("/auth/demo-preview/begin", preview_begin)
    app.router.add_post("/auth/demo-preview/complete", preview_complete)
    app.router.add_get("/api/state", api_state)
    app.router.add_get("/api/report", api_report)
    app.router.add_get("/ws", ws_handler)
    app.on_startup.append(on_start)
    app.on_cleanup.append(on_stop)
    return app


def main():
    rw.load_env(HERE / ".env")
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=int(os.environ.get("DEMO_PORT", "8080")))
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--code", default=os.environ.get("DEMO_CODE", "rewatch"))
    args = ap.parse_args()
    app = create_app(args.port, args.code)

    print("\n  ReWatch IoT — DEMO")
    print(f"  Open   http://localhost:{args.port}")
    print(f"  Passkey works on localhost, or use access code:  {args.code}")
    print("  Start/replay: devices at 20 s, AC spike at 30 s, then 20 s to acknowledge.")
    print("  Refresh reconnects; explicit Replay resets the scene, not saved reports.")
    print(f"  Real e-mail: {'ON' if rw.env_bool('DEMO_SEND_MAIL', False) else 'off (shown only)'}\n")
    web.run_app(app, host=args.host, port=args.port, print=None, access_log=None)


if __name__ == "__main__":
    main()
