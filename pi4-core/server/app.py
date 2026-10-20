"""ReWatch dashboard server — runs on the Pi 4 next to the threat engine.

  GET  /                 dashboard (lock screen until a passkey unlocks it)
  GET  /reports.html     everything that happened in the last 5 hours
  GET  /debug.html       raw vitals: bus rate, nodes, every frame
  GET  /manual.html      operator manual: bands, score model, playbooks
  GET  /assets/*         css / js / fonts (all self-hosted, zero CDN)
  WS   /ws               live bus -> browser, operator actions -> bus
  GET  /api/state        current threat state + nodes + devices
  GET  /api/report       ?hours=5  (max 48)
  POST /api/ack          {"id": "..."}
  GET  /healthz          liveness, no auth
  /auth/*                WebAuthn passkey + LAN access code (see auth.py)

Every data route needs a session cookie. Nothing in here invents data: the
browser only ever sees what arrived on MQTT from the real nodes.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sqlite3
import ssl
import sys
import time
from collections import deque
from pathlib import Path

from aiohttp import WSMsgType, web

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "common"))
import rewatch as rw  # noqa: E402
from iot import DevicePolicy  # noqa: E402

from .auth import SESSION_COOKIE, add_auth_routes  # noqa: E402
from .auth_db import AuthDB  # noqa: E402
from .devices import add_device_routes  # noqa: E402

LOG = logging.getLogger("rewatch.server")
VERSION = "1.0.0"
WEB = Path(__file__).resolve().parent.parent / "web"
PAGES = {"/": "index.html", "/index.html": "index.html", "/reports.html": "reports.html",
         "/debug.html": "debug.html", "/manual.html": "manual.html"}
CSP = ("default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
       "img-src 'self' data:; font-src 'self'; connect-src 'self' ws: wss:; "
       "frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
SEV_OF_LEVEL = {"ok": "info", "warn": "medium", "critical": "critical"}
NODE_LABEL = {"core": "Pi 4 Core", "sentinel": "Pi 3 Sentinel", "herald": "Pi 3 Herald",
              "indicator": "ESP32-C3 indicator", "rig": "ESP32-WROOM rig",
              "verifier": "Pi 4 Wi-Fi verifier"}


# ═════════════════════════════════════════════════════════════════════════════
# Event normalisation — the one place a bus message becomes a feed row
# (the browser has a byte-for-byte JavaScript twin in assets/core.js)
# ═════════════════════════════════════════════════════════════════════════════
class Normaliser:
    def __init__(self) -> None:
        self.node_online: dict[str, bool] = {}

    def __call__(self, t: str, d) -> dict | None:
        if not isinstance(d, dict):
            return None
        p = t.split("/")
        if len(p) < 2:
            return None
        ts = float(d.get("ts") or time.time())
        head = p[1]
        base = {"topic": t, "ts": ts}
        if head == "detect" and len(p) >= 3:
            if p[2] == "anomaly":
                if not d.get("changed"):
                    return None
                lvl = d.get("level", "ok")
                room = d.get("room") or d.get("device")
                return {**base, "id": f"an-{d.get('device')}-{int(ts * 1000)}", "kind": "anomaly",
                        "sev": SEV_OF_LEVEL.get(lvl, "info"), "device": d.get("device", ""),
                        "src": "", "title": (f"{room}: {d.get('reason', '')}" if lvl != "ok"
                                             else f"{room}: back to normal ({d.get('temp_c')} °C)"),
                        "node": "sentinel"}
            return {**base, "id": d.get("id") or f"ev-{int(ts * 1000)}", "kind": d.get("kind", p[2]),
                    "sev": d.get("sev", "medium"), "title": d.get("title", p[2]),
                    "src": d.get("src", ""), "device": d.get("device", ""),
                    "node": d.get("node", "sentinel"), "detail": d.get("detail", {})}
        if head == "alert":
            return {**base, "id": f"al-{d.get('id')}", "kind": "alert", "sev": "critical",
                    "title": f"RED incident — {d.get('title')}", "device": d.get("device", ""),
                    "src": d.get("src", ""), "incident": d.get("id"), "node": "core"}
        if head == "incident":
            st = d.get("state")
            words = {"acked": f"Acknowledged by {d.get('acked_by') or 'operator'}",
                     "auto": "No response in time — PURPLE automation",
                     "resolved": "Incident resolved — back to normal"}
            if st not in words:
                return None
            return {**base, "id": f"in-{d.get('id')}-{st}", "kind": "incident",
                    "sev": {"acked": "medium", "auto": "high", "resolved": "info"}[st],
                    "title": f"{words[st]} · {d.get('title', '')}", "incident": d.get("id"),
                    "device": d.get("device", ""), "src": "", "node": "core"}
        if head == "action":
            return {**base, "id": f"ac-{d.get('incident')}", "kind": "action", "sev": "high",
                    "title": ("Manual" if d.get("manual") else "Automatic") + " response — "
                    + d.get("summary", ""), "device": d.get("device", ""),
                    "src": d.get("src", ""), "incident": d.get("incident"), "node": "core"}
        if head == "mail" and len(p) >= 4 and p[2] == "result":
            ok = d.get("ok") is True
            to = ", ".join(d.get("to") or [])
            return {**base, "id": f"ml-{p[3]}-{d.get('kind')}-{int(ts)}", "kind": "mail",
                    "sev": "info" if ok else "medium",
                    "title": (f"SMTP accepted for {to} — “{d.get('subject', '')}” (delivery not confirmed)" if ok
                              else f"E-mail failed — {d.get('error', 'unknown error')}"),
                    "incident": d.get("id"), "device": "", "src": "", "node": "herald"}
        if head == "verify" and d.get("alarm"):
            return {**base, "id": f"vf-{d.get('device')}-{int(ts)}", "kind": "integrity",
                    "sev": "high", "device": d.get("device", ""), "src": "", "node": "core",
                    "title": f"Wi-Fi cross-check failed on {d.get('device')}: bus {d.get('mqtt_temp')} °C, "
                             f"device says {d.get('wifi_temp')} °C"}
        if head == "health" and len(p) >= 3:
            node = p[2]
            on = bool(d.get("online"))
            prev = self.node_online.get(node)
            self.node_online[node] = on
            if prev is None or prev == on:
                return None
            return {**base, "id": f"hl-{node}-{int(ts)}", "kind": "node",
                    "sev": "info" if on else "medium", "device": "", "src": "", "node": node,
                    "title": f"{NODE_LABEL.get(node, node)} {'back online' if on else 'went offline'}"}
        if head == "iot" and len(p) >= 4 and p[3] == "cmd":
            return {**base, "id": f"cm-{p[2]}-{int(ts * 1000)}", "kind": "command", "sev": "info",
                    "device": p[2], "src": "", "node": "core",
                    "title": f"Command requested → {p[2]}: {d.get('action', 'setpoint')} "
                             f"{d.get('value', d.get('setpoint'))} ({d.get('by', '')})"}
        if head == "rig" and len(p) >= 3 and p[2] == "cmd":
            return {**base, "id": f"rg-{int(ts * 1000)}", "kind": "rig", "sev": "info",
                    "device": d.get("device", ""), "src": "", "node": "rig",
                    "title": f"Test rig: {d.get('scenario')} {d.get('device', '')}".strip()}
        return None


# ═════════════════════════════════════════════════════════════════════════════
# Evidence store (SQLite on the Pi 4 SD card; the pen drive on Sentinel keeps
# the full raw log)
# ═════════════════════════════════════════════════════════════════════════════
class Store:
    SCHEMA = """
    CREATE TABLE IF NOT EXISTS events(id TEXT PRIMARY KEY, ts REAL, kind TEXT, sev TEXT,
        title TEXT, device TEXT, src TEXT, node TEXT, incident TEXT, json TEXT);
    CREATE INDEX IF NOT EXISTS events_ts ON events(ts);
    CREATE TABLE IF NOT EXISTS samples(ts REAL, score REAL, band TEXT);
    CREATE INDEX IF NOT EXISTS samples_ts ON samples(ts);
    CREATE TABLE IF NOT EXISTS incidents(id TEXT PRIMARY KEY, opened REAL, state TEXT,
        title TEXT, updated REAL, json TEXT);
    """

    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(str(path), check_same_thread=False)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.executescript(self.SCHEMA)

    def add_event(self, e: dict) -> None:
        self.db.execute("INSERT OR IGNORE INTO events VALUES(?,?,?,?,?,?,?,?,?,?)",
                        (e["id"], e["ts"], e["kind"], e["sev"], e["title"], e.get("device", ""),
                         e.get("src", ""), e.get("node", ""), e.get("incident"),
                         json.dumps(e, default=str)))
        self.db.commit()

    def add_sample(self, ts: float, score: float, band: str) -> None:
        self.db.execute("INSERT INTO samples VALUES(?,?,?)", (ts, score, band))
        self.db.execute("DELETE FROM samples WHERE ts < ?", (ts - 7 * 86400,))
        self.db.commit()

    def upsert_incident(self, d: dict) -> None:
        self.db.execute("INSERT INTO incidents VALUES(?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET "
                        "state=excluded.state, updated=excluded.updated, json=excluded.json",
                        (d["id"], d.get("opened", time.time()), d.get("state", "open"),
                         d.get("title", ""), time.time(), json.dumps(d, default=str)))
        self.db.commit()

    def events(self, since: float, limit: int = 5000) -> list[dict]:
        rows = self.db.execute("SELECT json FROM events WHERE ts >= ? ORDER BY ts DESC LIMIT ?",
                               (since, limit)).fetchall()
        return [json.loads(r[0]) for r in rows]

    def samples(self, since: float) -> list[tuple]:
        return self.db.execute("SELECT ts, score, band FROM samples WHERE ts >= ? ORDER BY ts",
                               (since,)).fetchall()

    def incidents(self, since: float) -> list[dict]:
        rows = self.db.execute("SELECT json FROM incidents WHERE opened >= ? OR updated >= ? "
                               "ORDER BY opened DESC", (since, since)).fetchall()
        return [json.loads(r[0]) for r in rows]


# ═════════════════════════════════════════════════════════════════════════════
# Live hub
# ═════════════════════════════════════════════════════════════════════════════
class Hub:
    def __init__(self, store: Store) -> None:
        self.store = store
        self.norm = Normaliser()
        self.clients: set[web.WebSocketResponse] = set()
        self.state: dict | None = None
        self.nodes: dict[str, dict] = {}
        self.telemetry: dict[str, dict] = {}
        self.verify: dict[str, dict] = {}
        self.history: deque = deque(maxlen=1800)   # 1 Hz for 30 min
        self.recent: deque = deque(maxlen=300)
        self.mqtt = None
        self.mqtt_ok = False
        self.msgs = 0
        self._last_sample = 0.0
        self._last_hist = 0.0
        for e in reversed(store.events(time.time() - 6 * 3600, 300)):
            self.recent.append(e)
        for ts, score, band in store.samples(time.time() - 1800):
            self.history.append([ts, score, band])

    def snapshot(self) -> dict:
        return {"state": self.state, "nodes": self.nodes, "telemetry": self.telemetry,
                "verify": self.verify, "history": list(self.history),
                "events": list(self.recent)[-200:], "mqtt": self.mqtt_ok, "version": VERSION,
                "server_ts": time.time()}

    async def broadcast(self, frame: dict) -> None:
        if not self.clients:
            return
        data = json.dumps(frame, separators=(",", ":"), default=str)
        dead = []
        for ws in self.clients:
            try:
                await ws.send_str(data)
            except (ConnectionError, RuntimeError):
                dead.append(ws)
        for ws in dead:
            self.clients.discard(ws)

    async def on_bus(self, t: str, d) -> None:
        self.msgs += 1
        now = time.time()
        p = t.split("/")
        if t == rw.topic("threat", "state") and isinstance(d, dict):
            self.state = d
            if now - self._last_hist >= 1.0:
                self._last_hist = now
                self.history.append([d.get("ts", now), d.get("score", 0), d.get("band")])
            if now - self._last_sample >= 5.0:
                self._last_sample = now
                self.store.add_sample(now, float(d.get("score", 0)), str(d.get("band")))
            if d.get("incident"):
                self.store.upsert_incident(d["incident"])
        elif len(p) >= 3 and p[1] == "health" and isinstance(d, dict):
            self.nodes[p[2]] = {**d, "rx": now}
        elif len(p) >= 4 and p[1] == "iot" and p[3] == "telemetry" and isinstance(d, dict):
            self.telemetry[p[2]] = {**d, "rx": now}
        elif len(p) >= 3 and p[1] == "verify" and isinstance(d, dict):
            self.verify[p[2]] = {**d, "rx": now}
        elif len(p) >= 3 and p[1] == "incident" and isinstance(d, dict):
            self.store.upsert_incident(d)
        e = self.norm(t, d)
        if e:
            self.store.add_event(e)
            self.recent.append(e)
            await self.broadcast({"t": "event", "e": e})
        await self.broadcast({"t": "bus", "topic": t, "d": d})

    async def publish(self, t: str, obj: dict) -> bool:
        if not self.mqtt:
            return False
        await self.mqtt.publish(t, json.dumps(obj), qos=1)
        return True


async def mqtt_loop(app: web.Application) -> None:
    import aiomqtt
    hub: Hub = app["hub"]
    host = rw.env("REWATCH_MQTT_HOST", "127.0.0.1")
    port = rw.env_int("REWATCH_MQTT_PORT", 1883)
    user = rw.env("REWATCH_MQTT_USER") or None
    pw = rw.env("REWATCH_MQTT_PASS") or None
    while True:
        try:
            async with aiomqtt.Client(host, port, username=user, password=pw,
                                      identifier=f"rewatch-dashboard-{os.getpid()}") as client:
                hub.mqtt, hub.mqtt_ok = client, True
                await client.subscribe(rw.topic("#"), qos=1)
                LOG.info("mqtt connected %s:%s", host, port)
                await hub.broadcast({"t": "mqtt", "ok": True})
                async for msg in client.messages:
                    try:
                        d = json.loads(msg.payload.decode()) if msg.payload else None
                    except (UnicodeDecodeError, json.JSONDecodeError):
                        continue
                    await hub.on_bus(msg.topic.value, d)
        except asyncio.CancelledError:
            raise
        except Exception as e:  # noqa: BLE001
            LOG.warning("mqtt: %s — retry in 3 s", e)
        hub.mqtt, hub.mqtt_ok = None, False
        await hub.broadcast({"t": "mqtt", "ok": False})
        await asyncio.sleep(3)


# ═════════════════════════════════════════════════════════════════════════════
# HTTP
# ═════════════════════════════════════════════════════════════════════════════
def session_ok(request: web.Request) -> bool:
    sid = request.cookies.get(SESSION_COOKIE)
    return bool(sid and request.app["auth_db"].validate_session(sid))


def need_session(request: web.Request) -> None:
    if not session_ok(request):
        raise web.HTTPUnauthorized(text="sign in first")


@web.middleware
async def security_headers(request: web.Request, handler):
    resp = await handler(request)
    resp.headers.setdefault("Content-Security-Policy", CSP)
    resp.headers.setdefault("X-Content-Type-Options", "nosniff")
    resp.headers.setdefault("Referrer-Policy", "no-referrer")
    if request.app["tls"]:
        resp.headers.setdefault("Strict-Transport-Security", "max-age=31536000")
    return resp


async def page(request: web.Request) -> web.StreamResponse:
    f = WEB / PAGES[request.path]
    resp = web.FileResponse(f)
    resp.headers["Cache-Control"] = "no-store"
    return resp


async def asset(request: web.Request) -> web.StreamResponse:
    tail = request.match_info["tail"]
    root = (WEB / "assets").resolve()
    target = (root / tail).resolve()
    if root not in target.parents or not target.is_file():
        raise web.HTTPNotFound()
    resp = web.FileResponse(target)
    resp.headers["Cache-Control"] = "public, max-age=300"
    return resp


async def healthz(request: web.Request) -> web.Response:
    hub: Hub = request.app["hub"]
    return web.json_response({"ok": True, "mqtt": hub.mqtt_ok, "ws_clients": len(hub.clients),
                              "msgs": hub.msgs, "version": VERSION})


async def api_state(request: web.Request) -> web.Response:
    need_session(request)
    return web.json_response(request.app["hub"].snapshot(), dumps=lambda o: json.dumps(o, default=str))


async def api_report(request: web.Request) -> web.Response:
    need_session(request)
    hub: Hub = request.app["hub"]
    try:
        hours = max(0.25, min(48.0, float(request.query.get("hours", "5"))))
    except ValueError:
        hours = 5.0
    now = time.time()
    since = now - hours * 3600
    events = hub.store.events(since)
    samples = hub.store.samples(since)
    band_time: dict[str, float] = {}
    for (t0, _, b), (t1, _, _) in zip(samples, samples[1:]):
        band_time[b] = band_time.get(b, 0) + min(t1 - t0, 30)
    per_min: dict[int, list] = {}
    for ts, score, band in samples:
        m = int(ts // 60) * 60
        cur = per_min.get(m)
        if not cur or score > cur[1]:
            per_min[m] = [m, score, band]
    counts: dict[str, int] = {}
    sev_counts: dict[str, int] = {}
    for e in events:
        counts[e["kind"]] = counts.get(e["kind"], 0) + 1
        sev_counts[e["sev"]] = sev_counts.get(e["sev"], 0) + 1
    return web.json_response({
        "from": since, "to": now, "hours": hours, "events": events,
        "incidents": hub.store.incidents(since), "counts": counts, "sev_counts": sev_counts,
        "band_time": band_time, "series": sorted(per_min.values()),
        "peak": max((s[1] for s in samples), default=0), "nodes": hub.nodes,
    })


async def api_ack(request: web.Request) -> web.Response:
    need_session(request)
    body = await request.json()
    ok = await request.app["hub"].publish(rw.topic("ack"), {"id": str(body.get("id", "")),
                                                          "by": "dashboard", "ts": time.time()})
    return web.json_response({"ok": ok})


async def ws_handler(request: web.Request) -> web.WebSocketResponse:
    if not session_ok(request):
        raise web.HTTPUnauthorized(text="sign in first")
    origin = request.headers.get("Origin", "")
    host = request.headers.get("Host", "")
    if origin and host and origin.split("://", 1)[-1] != host:
        raise web.HTTPForbidden(text="cross-origin websocket refused")
    hub: Hub = request.app["hub"]
    ws = web.WebSocketResponse(heartbeat=20, max_msg_size=64 * 1024)
    await ws.prepare(request)
    hub.clients.add(ws)
    await ws.send_str(json.dumps({"t": "hello", **hub.snapshot()}, default=str))
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
                await hub.publish(rw.topic("ack"), {"id": str(m.get("id", "")), "by": "dashboard",
                                                    "ts": time.time()})
            elif op == "respond":
                await hub.publish(rw.topic("respond"), {"id": str(m.get("id", "")), "ts": time.time()})
            elif op == "rig" and m.get("scenario") in ("ac-spike", "reset"):
                await hub.publish(rw.topic("rig", "cmd"), {"scenario": m["scenario"],
                                                           "device": str(m.get("device") or "room1-ac"),
                                                           "ts": time.time()})
            elif op == "mail-test":
                await hub.publish(rw.topic("mail", "test"), {"ts": time.time(), "by": "dashboard"})
    finally:
        hub.clients.discard(ws)
    return ws


async def on_startup(app: web.Application) -> None:
    app["mqtt_task"] = asyncio.create_task(mqtt_loop(app))


async def on_cleanup(app: web.Application) -> None:
    app["mqtt_task"].cancel()
    for ws in list(app["hub"].clients):
        await ws.close()


def build_app() -> web.Application:
    rw.load_env()
    data = Path(rw.env("REWATCH_DATA_DIR", "/var/lib/rewatch"))
    app = web.Application(middlewares=[security_headers], client_max_size=65536)
    tls = bool(rw.env("REWATCH_TLS_CERT") and rw.env("REWATCH_TLS_KEY"))
    app["tls"] = tls
    app["hub"] = Hub(Store(data / "rewatch.db"))
    app["auth_db"] = AuthDB(data / "auth.db")
    host = rw.env("REWATCH_HOSTNAME", "rewatch.local")
    port = rw.env_int("REWATCH_PORT", 443 if tls else 8080)
    app["auth_rp_id"] = rw.env("REWATCH_RP_ID", host)
    app["auth_rp_name"] = "ReWatch IoT"
    scheme = "https" if tls else "http"
    default_origins = [f"{scheme}://{host}" + ("" if port in (80, 443) else f":{port}"),
                       f"http://localhost:{port}", f"https://localhost:{port}"]
    app["auth_origins"] = [o.strip() for o in rw.env("REWATCH_ORIGINS", ",".join(default_origins))
                           .split(",") if o.strip()]
    app["auth_secure_cookies"] = tls
    app["demo_code"] = rw.env("REWATCH_ACCESS_CODE", "")
    add_auth_routes(app)
    add_device_routes(app, DevicePolicy.from_env(), lambda: app["hub"].telemetry, app["hub"].publish)
    for path in PAGES:
        app.router.add_get(path, page)
    app.router.add_get("/assets/{tail:.+}", asset)
    app.router.add_get("/healthz", healthz)
    app.router.add_get("/api/state", api_state)
    app.router.add_get("/api/report", api_report)
    app.router.add_post("/api/ack", api_ack)
    app.router.add_get("/ws", ws_handler)
    app.on_startup.append(on_startup)
    app.on_cleanup.append(on_cleanup)
    app["port"] = port
    return app


def main() -> None:
    rw.setup_logging("rewatch.server")
    app = build_app()
    ctx = None
    if app["tls"]:
        ctx = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
        ctx.load_cert_chain(rw.env("REWATCH_TLS_CERT"), rw.env("REWATCH_TLS_KEY"))
    LOG.info("dashboard on %s://0.0.0.0:%s (rp_id=%s)", "https" if ctx else "http", app["port"],
             app["auth_rp_id"])
    web.run_app(app, host=rw.env("REWATCH_BIND", "0.0.0.0"), port=app["port"], ssl_context=ctx,
                access_log=None, print=None)


if __name__ == "__main__":
    main()
