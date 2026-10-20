"""ReWatch IoT — shared contract and helpers used by every node.

One file on purpose: start.sh copies it to /opt/rewatch/common/ on every Pi,
so every service speaks exactly the same topics, bands and envelope.

Topic map (all under ``rewatch/``)
---------------------------------
iot/<device>/telemetry   IoT device -> bus        {"device","room","kind","temp_c","setpoint","power","ip"}
iot/<device>/cmd         Pi4 responder -> device  {"setpoint": 20, "by": "...", "reason": "..."}
detect/<kind>            Pi3 Sentinel -> bus      detection event (see make_event)
detect/anomaly/<device>  Pi3 Sentinel -> bus      condition: {"device","level":"ok|warn|critical",...}
verify/<device>          Pi4 verifier -> bus      Wi-Fi cross-check of telemetry
threat/state             Pi4 engine (retained)    score, band, incident, devices, nodes
alert/<id>               Pi4 engine -> Herald     new incident (Herald e-mails it)
incident/<id>            Pi4 engine               incident state changes (acked / auto / resolved)
action/<id>              Pi4 responder            automated or manual response that was executed
ack                      dashboard -> engine      {"id": "...", "by": "..."}
respond                  dashboard -> engine      {"id": "..."}  run the response now
mail/<id>                Herald -> bus            delivery result
mail/test                dashboard -> Herald      send a test e-mail
rig/cmd                  dashboard -> ESP32 rig   {"scenario": "ac-spike" | "reset", "device": "room1-ac"}
health/<node>            every node (retained)    heartbeat; LWT sets online=false
"""

from __future__ import annotations

import json
import logging
import os
import socket
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Callable, Iterable

PREFIX = "rewatch"
ENV_FILE = Path(os.environ.get("REWATCH_ENV", "/etc/rewatch/rewatch.env"))

# ── Bands ────────────────────────────────────────────────────────────────────
# GREEN normal · BLUE offline · YELLOW scan/suspicious · RED critical (blinking)
# PURPLE = a RED incident nobody acknowledged in time -> automated response.
GREEN, BLUE, YELLOW, RED, PURPLE = "GREEN", "BLUE", "YELLOW", "RED", "PURPLE"
BANDS = (GREEN, BLUE, YELLOW, RED, PURPLE)
YELLOW_AT = 30.0
RED_AT = 70.0

# Infrastructure nodes. If one of these stops heart-beating the band is BLUE.
NODES = ("core", "sentinel", "herald", "indicator", "rig")
REQUIRED_NODES = ("sentinel", "herald")
HEARTBEAT_S = 5.0
NODE_TIMEOUT_S = 20.0

SEVERITIES = ("info", "low", "medium", "high", "critical")


def topic(*parts: str) -> str:
    return "/".join((PREFIX,) + tuple(p.strip("/") for p in parts if p))


# ── Config ───────────────────────────────────────────────────────────────────
def load_env(path: Path | None = None) -> None:
    """Load KEY=VALUE lines from /etc/rewatch/rewatch.env into os.environ.

    Values already present in the environment win, so systemd overrides and
    ad-hoc `FOO=1 python ...` runs keep working.
    """
    p = path or ENV_FILE
    if not p.is_file():
        return
    for raw in p.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        k, v = k.strip(), v.strip()
        if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
            v = v[1:-1]
        os.environ.setdefault(k, v)


def env(name: str, default: str = "") -> str:
    return os.environ.get(name, default)


def env_float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, default))
    except ValueError:
        return default


def env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except ValueError:
        return default


def env_bool(name: str, default: bool = False) -> bool:
    return os.environ.get(name, "1" if default else "0").lower() in ("1", "true", "yes", "on")


def setup_logging(name: str) -> logging.Logger:
    logging.basicConfig(
        level=os.environ.get("REWATCH_LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s %(levelname)-5s %(name)s: %(message)s",
    )
    return logging.getLogger(name)


# ── Helpers ──────────────────────────────────────────────────────────────────
def now() -> float:
    return time.time()


def new_id(prefix: str = "ev") -> str:
    return f"{prefix}-{time.strftime('%H%M%S')}-{uuid.uuid4().hex[:6]}"


def local_ip() -> str:
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("10.255.255.255", 1))
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()


def iface_ip(iface: str) -> str | None:
    """IPv4 address of a named interface (Linux only), or None."""
    if not iface:
        return None
    try:
        import fcntl
        import struct
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        packed = fcntl.ioctl(s.fileno(), 0x8915, struct.pack("256s", iface[:15].encode()))
        return socket.inet_ntoa(packed[20:24])
    except OSError:
        return None


def band_for(score: float) -> str:
    if score >= RED_AT:
        return RED
    if score >= YELLOW_AT:
        return YELLOW
    return GREEN


def make_event(kind: str, sev: str, title: str, *, src: str = "", target: str = "",
               detail: dict | None = None, node: str = "sentinel",
               device: str = "") -> dict:
    """The one detection envelope every detector publishes on detect/<kind>."""
    if sev not in SEVERITIES:
        sev = "medium"
    return {
        "id": new_id(kind[:4]),
        "kind": kind,
        "sev": sev,
        "title": title,
        "src": src,
        "target": target,
        "device": device,
        "detail": detail or {},
        "node": node,
        "ts": now(),
    }


# ── MQTT ─────────────────────────────────────────────────────────────────────
class Bus:
    """Thin paho-mqtt wrapper: auto-reconnect, JSON in/out, retained heartbeat
    with a last-will so a node that dies shows up as offline within seconds."""

    def __init__(self, node: str, subscriptions: Iterable[str] = (),
                 on_message: Callable[[str, Any], None] | None = None,
                 heartbeat_info: Callable[[], dict] | None = None) -> None:
        import paho.mqtt.client as mqtt  # imported here so tests can stub it

        self.node = node
        self.log = logging.getLogger(f"rewatch.bus.{node}")
        self._subs = list(subscriptions)
        self._on_message = on_message
        self._hb_info = heartbeat_info
        self._started = time.monotonic()
        self.connected = threading.Event()

        host = env("REWATCH_MQTT_HOST", "127.0.0.1")
        port = env_int("REWATCH_MQTT_PORT", 1883)
        self.client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2,
                                  client_id=f"rewatch-{node}-{uuid.uuid4().hex[:4]}")
        user, pw = env("REWATCH_MQTT_USER"), env("REWATCH_MQTT_PASS")
        if user:
            self.client.username_pw_set(user, pw)
        self.client.will_set(topic("health", node),
                             json.dumps({"node": node, "online": False, "ts": now()}),
                             qos=1, retain=True)
        self.client.reconnect_delay_set(1, 10)
        self.client.on_connect = self._connect_cb
        self.client.on_disconnect = self._disconnect_cb
        self.client.on_message = self._message_cb
        self.client.connect_async(host, port, keepalive=15)
        self.client.loop_start()
        threading.Thread(target=self._heartbeat, name="heartbeat", daemon=True).start()

    # paho callbacks
    def _connect_cb(self, client, userdata, flags, reason_code, properties=None):
        if getattr(reason_code, "is_failure", False):
            self.log.warning("mqtt connect refused: %s", reason_code)
            return
        self.log.info("mqtt connected")
        for s in self._subs:
            client.subscribe(s, qos=1)
        self.connected.set()
        self.beat()

    def _disconnect_cb(self, client, userdata, flags, reason_code, properties=None):
        self.connected.clear()
        self.log.warning("mqtt disconnected (%s) — retrying", reason_code)

    def _message_cb(self, client, userdata, msg):
        if not self._on_message:
            return
        try:
            data = json.loads(msg.payload.decode("utf-8")) if msg.payload else None
        except (UnicodeDecodeError, json.JSONDecodeError):
            return
        try:
            self._on_message(msg.topic, data)
        except Exception:  # noqa: BLE001 - a bad message must not kill the loop
            self.log.exception("handler failed for %s", msg.topic)

    # API
    def publish(self, t: str, obj: Any, *, retain: bool = False, qos: int = 1) -> None:
        self.client.publish(t, json.dumps(obj, separators=(",", ":")), qos=qos, retain=retain)

    def beat(self) -> None:
        info = {}
        if self._hb_info:
            try:
                info = self._hb_info() or {}
            except Exception:  # noqa: BLE001
                info = {}
        self.publish(topic("health", self.node), {
            "node": self.node,
            "online": True,
            "ts": now(),
            "uptime": round(time.monotonic() - self._started),
            "host": socket.gethostname(),
            "ip": local_ip(),
            **info,
        }, retain=True)

    def _heartbeat(self) -> None:
        while True:
            time.sleep(HEARTBEAT_S)
            if self.connected.is_set():
                self.beat()

    def stop(self) -> None:
        try:
            self.publish(topic("health", self.node),
                         {"node": self.node, "online": False, "ts": now()}, retain=True)
            time.sleep(0.2)
        finally:
            self.client.loop_stop()
            self.client.disconnect()
