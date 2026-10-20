#!/usr/bin/env python3
"""ReWatch threat engine + responder — Raspberry Pi 4 (8 GB) on switch port 3.

The score model
---------------
score = clamp( max(condition points) + Σ impulse points · ½^(age / half-life) , 0, 100)

* **Conditions** last as long as the detector says they are true —
  an IoT device in `warn` (45 pts) or `critical` (90 pts).
* **Impulses** are one-off detections that fade: port scan 45, ARP sweep 35,
  ping sweep 30, new device 20, telemetry mismatch 40, flood 75.
  Half-life 60 s, so one nmap run is YELLOW for about a minute and fades.

Bands: GREEN < 30 ≤ YELLOW < 70 ≤ RED. BLUE when a required node (Sentinel or
Herald) has stopped heart-beating. PURPLE when a RED incident was not
acknowledged within ACK_TIMEOUT_S (default 120 s) and the responder acted.

Incident lifecycle
------------------
open (RED, e-mail sent by Herald, 2-minute countdown)
  ├─ acked      operator pressed Acknowledge on the dashboard
  ├─ auto       nobody answered -> PURPLE -> responder runs the playbook
  └─ resolved   score back under YELLOW for RESOLVE_HOLD_S

Playbooks
---------
* IoT anomaly on an AC unit -> publish iot/<device>/cmd {"setpoint": baseline}
* network attack (scan / flood) -> add the source IP to the nftables set
  `inet rewatch blocklist` on this Pi (only if RESPONDER_NFT=1)
"""

from __future__ import annotations

import math
import signal
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "common"))
import rewatch as rw  # noqa: E402

LOG = rw.setup_logging("rewatch.engine")

IMPULSE_POINTS = {
    "portscan": 45.0,
    "arpsweep": 35.0,
    "pingsweep": 30.0,
    "newdevice": 20.0,
    "integrity": 40.0,
    "flood": 75.0,
    "device-offline": 10.0,
}
CONDITION_POINTS = {"ok": 0.0, "warn": 45.0, "critical": 90.0}


@dataclass
class Impulse:
    kind: str
    points: float
    ts: float
    ev: dict


@dataclass
class Incident:
    id: str
    opened: float
    deadline: float
    title: str
    cause: dict
    device: str = ""
    src: str = ""
    state: str = "open"           # open | acked | auto | resolved
    acked_by: str = ""
    acked_ts: float | None = None
    action: dict | None = None
    resolved_ts: float | None = None
    peak: float = 0.0
    timeline: list = field(default_factory=list)

    def public(self, t: float) -> dict:
        return {
            "id": self.id, "state": self.state, "title": self.title,
            "opened": self.opened, "deadline": self.deadline,
            "remaining": max(0.0, round(self.deadline - t, 1)) if self.state == "open" else 0,
            "device": self.device, "src": self.src, "acked_by": self.acked_by,
            "acked_ts": self.acked_ts, "action": self.action, "resolved_ts": self.resolved_ts,
            "peak": round(self.peak, 1), "cause": self.cause, "timeline": self.timeline,
        }


class ThreatEngine:
    """Pure state machine. `tick(t)` returns the published state; messages go
    in through `on_message`. The MQTT side lives in main() so this is testable."""

    def __init__(self, *, half_life: float = 60.0, ack_timeout: float = 120.0,
                 purple_hold: float = 20.0, resolve_hold: float = 8.0,
                 baseline_setpoint: float = 20.0) -> None:
        self.half_life = half_life
        self.ack_timeout = ack_timeout
        self.purple_hold = purple_hold
        self.resolve_hold = resolve_hold
        self.baseline = baseline_setpoint
        self.impulses: list[Impulse] = []
        self.conditions: dict[str, dict] = {}      # device -> anomaly condition
        self.devices: dict[str, dict] = {}         # device -> last telemetry (+verify)
        self.nodes: dict[str, dict] = {}           # node -> last heartbeat
        self.incident: Incident | None = None
        self.recent: list[Incident] = []
        self.band = rw.GREEN
        self.score = 0.0
        self._band_since = 0.0
        self._calm_since: float | None = None
        self._purple_until = 0.0
        self.out: list[tuple[str, dict, bool]] = []   # (topic, payload, retain) to publish
        self.started = rw.now()

    # ── inputs ────────────────────────────────────────────────────────────
    def on_message(self, t: str, d, now: float | None = None) -> None:
        now = rw.now() if now is None else now
        if not isinstance(d, dict):
            return
        parts = t.split("/")
        if len(parts) < 2 or parts[0] != rw.PREFIX:
            return
        head = parts[1]
        if head == "detect":
            kind = parts[2] if len(parts) > 2 else ""
            if kind == "anomaly":
                dev = d.get("device") or (parts[3] if len(parts) > 3 else "")
                if dev:
                    if d.get("level", "ok") == "ok":
                        self.conditions.pop(dev, None)
                    else:
                        self.conditions[dev] = {**d, "rx": now}
                return
            pts = IMPULSE_POINTS.get(kind)
            if pts:
                self.impulses.append(Impulse(kind, pts, now, d))
        elif head == "iot" and len(parts) >= 4 and parts[3] == "telemetry":
            dev = parts[2]
            self.devices[dev] = {**self.devices.get(dev, {}), **d, "rx": now}
        elif head == "verify" and len(parts) >= 3:
            dev = parts[2]
            self.devices.setdefault(dev, {})["verify"] = {**d, "rx": now}
            if d.get("alarm"):
                self.impulses.append(Impulse("integrity", IMPULSE_POINTS["integrity"], now, {
                    **d, "title": f"Telemetry mismatch on {dev}: bus {d.get('mqtt_temp')} °C "
                                  f"vs Wi-Fi {d.get('wifi_temp')} °C"}))
        elif head == "health" and len(parts) >= 3:
            self.nodes[parts[2]] = {**d, "rx": now}
        elif head == "ack":
            self.ack(str(d.get("id", "")), str(d.get("by", "dashboard")), now)
        elif head == "respond":
            self.respond(str(d.get("id", "")), now, manual=True)

    # ── operator actions ─────────────────────────────────────────────────
    def ack(self, inc_id: str, by: str, now: float) -> bool:
        inc = self.incident
        if not inc or (inc_id and inc_id != inc.id) or inc.state != "open":
            return False
        inc.state, inc.acked_by, inc.acked_ts = "acked", by, now
        inc.timeline.append({"ts": now, "what": f"acknowledged by {by}"})
        LOG.info("incident %s acknowledged by %s", inc.id, by)
        self._emit_incident(inc)
        return True

    def respond(self, inc_id: str, now: float, manual: bool = False) -> bool:
        inc = self.incident
        if not inc or (inc_id and inc_id != inc.id) or inc.action:
            return False
        action = self.playbook(inc, now)
        inc.action = action
        inc.timeline.append({"ts": now, "what": ("manual" if manual else "automatic")
                             + f" response: {action['summary']}"})
        if not manual:
            inc.state = "auto"
            self._purple_until = now + self.purple_hold
        self.out.append((rw.topic("action", inc.id), {**action, "incident": inc.id,
                                                      "manual": manual}, False))
        self._emit_incident(inc)
        return True

    def playbook(self, inc: Incident, now: float) -> dict:
        if inc.device:
            dev = self.devices.get(inc.device, {})
            target = float(dev.get("baseline") or self.baseline)
            self.out.append((rw.topic("iot", inc.device, "cmd"), {
                "setpoint": target, "by": "rewatch-responder", "reason": inc.title,
                "incident": inc.id, "ts": now}, False))
            room = dev.get("room") or inc.device
            return {"type": "setpoint", "device": inc.device, "from": dev.get("temp_c"),
                    "to": target, "ts": now,
                    "summary": f"{room}: AC forced back to {target:.0f} °C"}
        if inc.src:
            ok = nft_block(inc.src)
            return {"type": "block", "src": inc.src, "ts": now, "applied": ok,
                    "summary": f"source {inc.src} " + ("blocked on Pi4 firewall" if ok
                                                       else "flagged (nft blocking disabled)")}
        return {"type": "notify", "ts": now, "summary": "escalated — no playbook for this cause"}

    # ── the clock ────────────────────────────────────────────────────────
    def compute_score(self, now: float) -> tuple[float, list[dict]]:
        contrib: list[dict] = []
        cond_max = 0.0
        for dev, c in self.conditions.items():
            pts = CONDITION_POINTS.get(c.get("level", "ok"), 0.0)
            cond_max = max(cond_max, pts)
            if pts:
                contrib.append({"src": "anomaly", "device": dev, "points": pts,
                                "title": f"{c.get('room') or dev}: {c.get('reason', '')}",
                                "level": c.get("level")})
        keep: list[Impulse] = []
        imp_sum = 0.0
        for imp in self.impulses:
            age = now - imp.ts
            pts = imp.points * math.pow(0.5, age / self.half_life)
            if pts < 0.5:
                continue
            keep.append(imp)
            imp_sum += pts
            contrib.append({"src": imp.kind, "points": round(pts, 1),
                            "title": imp.ev.get("title", imp.kind), "age": round(age)})
        self.impulses = keep
        contrib.sort(key=lambda c: -c["points"])
        return min(100.0, cond_max + imp_sum), contrib

    def offline_nodes(self, now: float) -> list[str]:
        out = []
        for n in rw.REQUIRED_NODES:
            h = self.nodes.get(n)
            if not h:
                if now - self.started > rw.NODE_TIMEOUT_S:
                    out.append(n)
                continue
            if not h.get("online", False) or now - h.get("rx", 0) > rw.NODE_TIMEOUT_S:
                out.append(n)
        return out

    def _cause(self, contrib: list[dict]) -> dict:
        return contrib[0] if contrib else {"src": "unknown", "title": "risk threshold crossed"}

    def tick(self, now: float | None = None) -> dict:
        now = rw.now() if now is None else now
        score, contrib = self.compute_score(now)
        self.score = score
        offline = self.offline_nodes(now)

        # incidents
        inc = self.incident
        if score >= rw.RED_AT and inc is None:
            cause = self._cause(contrib)
            title = cause.get("title", "Critical threat")
            inc = Incident(id=rw.new_id("inc"), opened=now, deadline=now + self.ack_timeout,
                           title=title, cause=cause, device=cause.get("device", ""),
                           src=next((i.ev.get("src", "") for i in self.impulses
                                     if i.kind == cause.get("src")), ""))
            inc.timeline.append({"ts": now, "what": f"RED — {title}"})
            self.incident = inc
            LOG.warning("INCIDENT %s opened: %s", inc.id, title)
            self.out.append((rw.topic("alert", inc.id), {
                "id": inc.id, "band": rw.RED, "sev": "critical", "title": title,
                "score": round(score), "device": inc.device, "src": inc.src,
                "room": self.devices.get(inc.device, {}).get("room", ""),
                "temp_c": self.devices.get(inc.device, {}).get("temp_c"),
                "deadline": inc.deadline, "ack_timeout": self.ack_timeout,
                "planned_action": self._planned(inc), "ts": now}, False))
            self._emit_incident(inc)
        if inc:
            inc.peak = max(inc.peak, score)
            if inc.state == "open" and now >= inc.deadline:
                inc.timeline.append({"ts": now, "what": "no response in time — PURPLE"})
                LOG.warning("incident %s unacknowledged — automated response", inc.id)
                self.respond(inc.id, now, manual=False)
            # resolve once calm
            if score < rw.YELLOW_AT and now >= self._purple_until:
                self._calm_since = self._calm_since or now
                if now - self._calm_since >= self.resolve_hold:
                    inc.state, inc.resolved_ts = "resolved", now
                    inc.timeline.append({"ts": now, "what": "resolved — back to normal"})
                    self._emit_incident(inc)
                    self.recent = ([inc] + self.recent)[:10]
                    self.incident = None
                    LOG.info("incident %s resolved", inc.id)
            else:
                self._calm_since = None

        # band
        if self.incident and now < self._purple_until:
            band = rw.PURPLE
        elif self.incident and self.incident.state == "auto" and score >= rw.YELLOW_AT:
            band = rw.PURPLE
        elif score >= rw.RED_AT or (self.incident and self.incident.state in ("open", "acked")
                                    and score >= rw.YELLOW_AT):
            band = rw.RED
        elif offline:
            band = rw.BLUE
        else:
            band = rw.band_for(score)
            # hysteresis on the way down: 3 points and 3 seconds
            if self.band == rw.YELLOW and band == rw.GREEN and \
                    (score > rw.YELLOW_AT - 3 or now - self._band_since < 3):
                band = rw.YELLOW
        if band != self.band:
            LOG.info("band %s -> %s (score %.0f)", self.band, band, score)
            self.band, self._band_since = band, now

        reason = (f"{', '.join(offline)} offline" if band == rw.BLUE
                  else contrib[0]["title"] if contrib else "All quiet — nothing above noise")
        state = {
            "score": round(score, 1), "band": band, "reason": reason, "ts": now,
            "contrib": contrib[:8], "offline": offline,
            "incident": self.incident.public(now) if self.incident else None,
            "recent": [i.public(now) for i in self.recent[:5]],
            "thresholds": {"yellow": rw.YELLOW_AT, "red": rw.RED_AT,
                           "ack_timeout": self.ack_timeout, "half_life": self.half_life},
            "devices": {k: {kk: v.get(kk) for kk in ("room", "kind", "temp_c", "setpoint", "power",
                                                     "ip", "rx")}
                        | {"level": self.conditions.get(k, {}).get("level", "ok"),
                           "verified": (v.get("verify") or {}).get("ok")}
                        for k, v in self.devices.items()},
        }
        self.out.append((rw.topic("threat", "state"), state, True))
        return state

    def _planned(self, inc: Incident) -> str:
        if inc.device:
            room = self.devices.get(inc.device, {}).get("room") or inc.device
            return f"force {room} AC back to {self.baseline:.0f} °C"
        if inc.src:
            return f"block {inc.src} on the ReWatch firewall"
        return "escalate"

    def _emit_incident(self, inc: Incident) -> None:
        self.out.append((rw.topic("incident", inc.id), inc.public(rw.now()), False))


def nft_block(ip: str) -> bool:
    if not rw.env_bool("RESPONDER_NFT", False):
        return False
    try:
        subprocess.run(["nft", "add", "element", "inet", "rewatch", "blocklist", f"{{ {ip} }}"],
                       check=True, capture_output=True, timeout=5)
        LOG.warning("blocked %s via nftables", ip)
        return True
    except (OSError, subprocess.SubprocessError) as e:
        LOG.error("nft block failed: %s", e)
        return False


def main() -> None:
    rw.load_env()
    eng = ThreatEngine(half_life=rw.env_float("ENGINE_HALF_LIFE_S", 60),
                       ack_timeout=rw.env_float("ACK_TIMEOUT_S", 120),
                       purple_hold=rw.env_float("PURPLE_HOLD_S", 20),
                       baseline_setpoint=rw.env_float("AC_BASELINE_C", 20))
    lock = threading.Lock()

    def on_msg(t, d):
        with lock:
            eng.on_message(t, d)

    bus = rw.Bus("core", subscriptions=[rw.topic("detect", "#"), rw.topic("iot", "+", "telemetry"),
                                         rw.topic("verify", "#"), rw.topic("health", "+"),
                                         rw.topic("ack"), rw.topic("respond")],
                 on_message=on_msg,
                 heartbeat_info=lambda: {"role": "threat engine", "band": eng.band,
                                         "score": round(eng.score)})
    stop = threading.Event()
    signal.signal(signal.SIGTERM, lambda *_: stop.set())
    signal.signal(signal.SIGINT, lambda *_: stop.set())
    LOG.info("threat engine up (ack timeout %.0fs)", eng.ack_timeout)
    while not stop.wait(0.5):
        with lock:
            eng.tick()
            out, eng.out = eng.out, []
        for t, payload, retain in out:
            bus.publish(t, payload, retain=retain)
    bus.stop()


if __name__ == "__main__":
    main()
