import asyncio
from pathlib import Path
import sys
import tempfile
import unittest

from aiohttp import CookieJar, WSServerHandshakeError
from aiohttp.test_utils import TestClient, TestServer

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "demo"))
import demo_server  # noqa: E402
from server.auth import reset_rate_limits  # noqa: E402


class DemoHTTPTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        reset_rate_limits()
        self.directory = tempfile.TemporaryDirectory()
        self.app = demo_server.create_app(auth_path=Path(self.directory.name) / "auth.db")
        self.client = TestClient(TestServer(self.app), cookie_jar=CookieJar(unsafe=True))
        await self.client.start_server()

    async def asyncTearDown(self):
        await self.client.close()
        self.directory.cleanup()

    async def login(self):
        response = await self.client.post("/auth/demo", json={"code": "rewatch"})
        self.assertEqual(response.status, 200)

    async def hello(self, ws):
        async with asyncio.timeout(3):
            while True:
                frame = await ws.receive_json()
                if frame.get("t") == "hello":
                    return frame

    async def test_pages_headers_and_auth(self):
        for page in ("/", "/debug.html", "/manual.html", "/reports.html"):
            response = await self.client.get(page)
            self.assertEqual(response.status, 200)
            self.assertIn("frame-ancestors 'none'", response.headers["Content-Security-Policy"])
        self.assertEqual((await self.client.get("/api/state")).status, 401)
        self.assertEqual((await self.client.post("/auth/demo", json=[])).status, 400)
        await self.login()
        snapshot = await (await self.client.get("/api/state")).json()
        self.assertIs(snapshot["simulation"], True)
        self.assertIs(snapshot["mqtt"], False)
        self.assertEqual((await self.client.get("/api/report")).status, 200)

    async def test_websocket_replay_reconnect_and_bad_frames(self):
        await self.login()
        async with self.client.ws_connect("/ws?replay=1") as ws:
            first = await self.hello(ws)
            self.assertEqual(first["telemetry"], {})
            generation = self.app["sim"].generation
            await ws.send_str("[]")
            await ws.send_str("not json")
            await ws.send_json({"op": "rig", "scenario": "ac-spike"})
            await ws.send_json({"op": "replay"})
            self.assertEqual((await self.hello(ws))["telemetry"], {})
            self.assertEqual(self.app["sim"].generation, generation + 1)
        async with self.client.ws_connect("/ws") as ws:
            await self.hello(ws)
            self.assertEqual(self.app["sim"].generation, generation + 1)

    async def test_cross_origin_controls_denied(self):
        response = await self.client.post("/auth/demo", json={"code": "rewatch"},
                                          headers={"Origin": "https://untrusted.example"})
        self.assertEqual(response.status, 403)
        await self.login()
        with self.assertRaises(WSServerHandshakeError) as raised:
            await self.client.ws_connect("/ws", origin="https://untrusted.example")
        self.assertEqual(raised.exception.status, 403)

    async def test_report_keeps_simulation_after_replay_and_restart(self):
        await self.login()
        sim = self.app["sim"]
        sim.rig("ac-spike")
        now = demo_server.time.time()
        for i in range(30):
            sim.tick(now + i * 0.5)
        before = await (await self.client.get("/api/report?hours=5")).json()
        self.assertTrue(before["events"])
        self.assertTrue(before["incidents"])
        self.assertGreaterEqual(before["peak"], 70)
        sim.replay(now + 20)
        after = await (await self.client.get("/api/report?hours=5")).json()
        self.assertEqual({e["id"] for e in before["events"]},
                         {e["id"] for e in after["events"]})
        self.assertGreaterEqual(after["peak"], 70)
        await self.client.close()
        self.app = demo_server.create_app(auth_path=Path(self.directory.name) / "auth.db")
        self.client = TestClient(TestServer(self.app), cookie_jar=CookieJar(unsafe=True))
        await self.client.start_server()
        await self.login()
        restored = await (await self.client.get("/api/report?hours=5")).json()
        self.assertTrue(restored["incidents"])
        self.assertGreaterEqual(restored["peak"], 70)

    async def test_initial_websocket_starts_and_refresh_does_not_reset(self):
        await self.login()
        async with self.client.ws_connect("/ws") as ws:
            await self.hello(ws)
            self.assertIsNotNone(self.app["sim"].started_at)
            self.app["sim"].rig("ac-spike")
        generation = self.app["sim"].generation
        async with self.client.ws_connect("/ws") as ws:
            await self.hello(ws)
            self.assertEqual(self.app["sim"].generation, generation)
            self.assertTrue(self.app["sim"].rooms["room1-ac"]["spiked"])
        script = (demo_server.WEB / "assets/live.js").read_text()
        self.assertNotIn('"?replay=1"', script)

    async def test_preview_is_opt_in_and_explicitly_not_verified(self):
        response = await self.client.post("/auth/demo-preview/complete", json={})
        self.assertEqual(response.status, 404)
        self.app["passkey_preview"] = True
        self.app["auth_origins"].append(str(self.client.make_url("/")).rstrip("/"))
        options = await self.client.post("/auth/demo-preview/begin", json={})
        self.assertEqual(options.status, 200)
        self.assertEqual(len((await options.json())["challenge"]), 43)
        response = await self.client.post("/auth/demo-preview/complete", json={})
        self.assertEqual(response.status, 200)
        self.assertIs((await response.json())["verified"], False)
        self.assertEqual((await self.client.get("/api/state")).status, 200)

    async def test_production_rejects_unknown_passkey_even_with_preview_enabled(self):
        self.app["passkey_preview"] = True
        response = await self.client.post("/auth/login/complete", json={"id": "not-a-credential"})
        self.assertIn(response.status, (400, 401))
