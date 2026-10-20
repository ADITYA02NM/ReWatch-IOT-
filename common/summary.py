"""Bounded five-minute system summaries shared by Herald and the demo."""
from collections import deque
import threading
import time


class ReportWindow:
    def __init__(self, start: float | None = None) -> None:
        self.since = time.time() if start is None else start
        self.state: dict = {}
        self.state_ts = 0.0
        self.nodes: dict = {}
        self.events: deque = deque(maxlen=2000)
        self.samples: deque = deque(maxlen=2000)
        self.lock = threading.Lock()

    def observe(self, topic: str, data: dict, now: float) -> None:
        if not isinstance(data, dict):
            return
        parts = topic.split("/")
        with self.lock:
            if topic.endswith("/threat/state"):
                self.state, self.state_ts = data, now
                self.samples.append((now, data.get("score", 0)))
            elif len(parts) == 3 and parts[1] == "health":
                if len(self.nodes) < 128 or parts[2] in self.nodes:
                    self.nodes[parts[2]] = {"online": data.get("online") is True, "rx": now}
            elif len(parts) >= 3 and parts[1] in ("detect", "action"):
                if (parts[1] != "detect" or parts[2] != "anomaly"
                        or (data.get("changed") and data.get("active") is True)):
                    self.events.append((now, parts[1]))

    def poll(self, now: float) -> dict | None:
        with self.lock:
            if now - self.since < 300:
                return None
            events = [kind for ts, kind in self.events if ts >= self.since]
            fresh = bool(self.state) and now - self.state_ts <= 20
            incident = self.state.get("incident") or {}
            report = {"id": f"summary-{int(now)}", "kind": "summary", "ts": now,
                      "from": self.since, "to": now, "band": self.state.get("band", "UNKNOWN") if fresh else "UNKNOWN",
                      "score": self.state.get("score", 0), "state_received": fresh,
                      "peak": max((score for ts, score in self.samples if ts >= self.since), default=0),
                      "devices": len(self.state.get("devices") or {}),
                      "offline": sorted(n for n, h in self.nodes.items() if not h["online"] or now - h["rx"] > 20),
                      "nodes_seen": len(self.nodes), "detections": events.count("detect"),
                      "responses": events.count("action"), "incident": incident.get("state", "none")}
            self.since = now
            self.events.clear()
            self.samples.clear()
            return report
