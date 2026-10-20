"""HTTP contracts for explicitly authorized MQTT device commands."""

import asyncio
import json
import math
from pathlib import Path
import tempfile
import unittest

from aiohttp import CookieJar, web
from aiohttp.test_utils import TestClient, TestServer

import rewatch as rw
from iot import DevicePolicy
from server.auth import SESSION_COOKIE
from server.auth_db import AuthDB
from server.devices import add_device_routes


class DeviceRoutesTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.db = AuthDB(Path(directory.name) / "auth.db")
        self.addCleanup(self.db.close)
        self.db.save_credential("test-operator", b"test-public-key", 0)
        self.config = {
            "room1-ac": {"kind": "ac", "enabled": True, "actions": ["setpoint"]},
            "hall-light": {"kind": "light", "enabled": True,
                           "actions": ["power", "brightness"]},
            "fan": {"kind": "fan", "enabled": True, "actions": ["power", "speed"]},
            "camera": {"kind": "camera", "enabled": True, "actions": ["recording"]},
            "door": {"kind": "door", "enabled": True, "actions": ["lock"]},
            "disabled": {"kind": "ac", "enabled": False, "actions": ["setpoint"]},
            "observe-only": {"kind": "ac", "enabled": True, "actions": []},
        }
        self.telemetry = {}
        self.published = []
        self.transport_result = True
        self.transport_error = None

        async def publish(topic, payload):
            self.published.append((topic, dict(payload)))
            await asyncio.sleep(0)
            if self.transport_error is not None:
                raise self.transport_error
            return self.transport_result

        self.app = web.Application()
        self.app["auth_db"] = self.db
        self.app["auth_origins"] = ["https://dashboard.example"]
        add_device_routes(self.app, DevicePolicy(self.config),
                          lambda: self.telemetry, publish)
        self.client = TestClient(TestServer(self.app), cookie_jar=CookieJar(unsafe=True))
        self.addAsyncCleanup(self.client.close)
        await self.client.start_server()

    def login(self, **session_options):
        sid = self.db.create_session("test-operator", **session_options)
        self.client.session.cookie_jar.update_cookies(
            {SESSION_COOKIE: sid}, response_url=self.client.make_url("/"))
        return sid

    @staticmethod
    def command(**overrides):
        return {"device": "room1-ac", "action": "setpoint", "value": 22,
                **overrides}

    async def assert_rejected(self, payload, status=400, **options):
        before = len(self.published)
        audit_before = self.db.read_audit()
        response = await self.client.post("/api/control", json=payload, **options)
        self.assertEqual(response.status, status, await response.text())
        self.assertEqual(len(self.published), before)
        self.assertEqual(self.db.read_audit(), audit_before)

    async def test_inventory_and_control_require_a_session(self):
        for cookie in (None, "invalid-session"):
            with self.subTest(cookie=cookie):
                self.client.session.cookie_jar.clear()
                if cookie:
                    self.client.session.cookie_jar.update_cookies(
                        {SESSION_COOKIE: cookie}, response_url=self.client.make_url("/"))
                response = await self.client.get("/api/devices")
                self.assertEqual(response.status, 401)
                await self.assert_rejected(self.command(), status=401)

    async def test_expired_and_revoked_sessions_cannot_access_routes(self):
        for state in ("expired", "revoked"):
            with self.subTest(state=state):
                sid = self.login(ttl=-1 if state == "expired" else 3600)
                if state == "revoked":
                    self.db.revoke_session(sid)
                self.assertEqual((await self.client.get("/api/devices")).status, 401)
                await self.assert_rejected(self.command(), status=401)

    async def test_inventory_uses_configuration_not_claimed_telemetry_permissions(self):
        self.login()
        forged = {"kind": "door", "enabled": True, "actions": ["setpoint", "unlock"],
                  "control": True, "adapter": "mqtt", "room": "Observed room",
                  "firmware": "untrusted-1", "ip": "192.0.2.10"}
        self.telemetry.update({device: dict(forged) for device in
                               ("rogue", "disabled", "observe-only", "room1-ac")})
        response = await self.client.get("/api/devices")
        self.assertEqual(response.status, 200)
        body = await response.json()
        self.assertIs(body["simulation"], False)
        rows = {row["device"]: row for row in body["devices"]}
        self.assertEqual(set(rows), set(self.config) | {"rogue"})
        for device in ("rogue", "disabled", "observe-only"):
            with self.subTest(device=device):
                self.assertIs(rows[device]["control"], False)
                self.assertEqual(rows[device]["actions"], [])
                self.assertIs(rows[device]["observed"], True)
                await self.assert_rejected(self.command(device=device))
        self.assertEqual(rows["rogue"]["adapter"], "observe-only")
        self.assertEqual(rows["room1-ac"]["kind"], "ac")
        self.assertEqual(rows["room1-ac"]["actions"], ["setpoint"])
        self.assertEqual(rows["room1-ac"]["firmware"], "untrusted-1")
        self.assertEqual(rows["room1-ac"]["room"], "Observed room")
        self.assertEqual(rows["room1-ac"]["ip"], "192.0.2.10")
        self.assertIs(rows["hall-light"]["observed"], False)
        await self.assert_rejected(self.command(action="unlock", value=True, confirmed=True))
        self.assertEqual(self.published, [])

    async def test_cross_origin_inventory_and_control_are_forbidden(self):
        self.login()
        headers = {"Origin": "https://evil.example"}
        response = await self.client.get("/api/devices", headers=headers)
        self.assertEqual(response.status, 403)
        await self.assert_rejected(self.command(), status=403, headers=headers)

    async def test_non_json_content_types_are_unsupported(self):
        self.login()
        for content_type in ("text/plain", "application/x-www-form-urlencoded",
                             "application/octet-stream"):
            with self.subTest(content_type=content_type):
                response = await self.client.post(
                    "/api/control", data=json.dumps(self.command()),
                    headers={"Content-Type": content_type})
                self.assertEqual(response.status, 415, await response.text())
        self.assertEqual(self.published, [])
        self.assertEqual(self.db.read_audit(), [])

    async def test_malformed_json_and_invalid_utf8_are_bad_requests(self):
        self.login()
        for data in (b"", b"{", b'{"device":', b'{"value": 22,}', b"\xff"):
            with self.subTest(data=data):
                response = await self.client.post(
                    "/api/control", data=data, headers={"Content-Type": "application/json"})
                self.assertEqual(response.status, 400, await response.text())
        self.assertEqual(self.published, [])
        self.assertEqual(self.db.read_audit(), [])

    async def test_payload_must_be_an_object_with_required_fields(self):
        self.login()
        for payload in (None, [], [self.command()], "command", True, 42, {},
                        {"action": "setpoint", "value": 22},
                        {"device": "room1-ac", "value": 22},
                        {"device": "room1-ac", "action": "setpoint"}):
            with self.subTest(payload=payload):
                # Send literal JSON null, not aiohttp's absent json=None body.
                if payload is None:
                    response = await self.client.post(
                        "/api/control", data="null",
                        headers={"Content-Type": "application/json"})
                    self.assertEqual(response.status, 400)
                else:
                    await self.assert_rejected(payload)
        self.assertEqual(self.published, [])
        self.assertEqual(self.db.read_audit(), [])

    async def test_invalid_device_and_action_types_and_unsafe_identifiers(self):
        self.login()
        for device in (None, True, 7, [], {}, "", "../door", "a/b", "a\\b", "+", "#",
                       "room#", "room+", "é-😀", "'; DROP TABLE sessions;--", "a" * 65,
                       "a" * 10_000, "not-enrolled"):
            with self.subTest(device=device):
                await self.assert_rejected(self.command(device=device))
        for action in (None, True, 7, [], {}, "", "reboot", "power", "setpoint/../../cmd"):
            with self.subTest(action=action):
                await self.assert_rejected(self.command(action=action))

    async def test_numeric_actions_reject_unsafe_values(self):
        self.login()
        for device, action, low, high in (("room1-ac", "setpoint", 16, 30),
                                          ("hall-light", "brightness", 0, 100),
                                          ("fan", "speed", 0, 100)):
            for value in (None, True, False, "22", [], {}, float("nan"), float("inf"),
                          -float("inf"), low - 0.01, high + 0.01):
                with self.subTest(device=device, action=action, value=value):
                    await self.assert_rejected(self.command(device=device, action=action,
                                                            value=value))

    async def test_boolean_actions_require_boolean_values(self):
        self.login()
        for device, action in (("hall-light", "power"), ("fan", "power"),
                               ("camera", "recording")):
            for value in (None, 0, 1, "true", "false", [], {}):
                with self.subTest(device=device, value=value):
                    await self.assert_rejected(self.command(device=device, action=action,
                                                            value=value))

    async def test_door_unlock_and_nonliteral_confirmation_are_rejected(self):
        self.login()
        for action, value, confirmed in (
            ("unlock", True, True), ("unlock", False, True),
            ("lock", False, True), ("lock", 1, True), ("lock", "true", True),
            ("lock", None, True), ("lock", True, False), ("lock", True, None),
            ("lock", True, 1), ("lock", True, "true"),
        ):
            with self.subTest(action=action, value=value, confirmed=confirmed):
                await self.assert_rejected(self.command(device="door", action=action,
                                                        value=value, confirmed=confirmed))
        await self.assert_rejected(self.command(device="door", action="lock", value=True))

    async def test_enabled_commands_publish_envelope_and_audit_with_202(self):
        self.login()
        cases = [("room1-ac", "setpoint", value) for value in (16, 22.5, 30)]
        cases += [("hall-light", "brightness", value) for value in (0, 42.5, 100)]
        cases += [("fan", "speed", value) for value in (0, 25.5, 100)]
        cases += [(device, action, value) for device, action in
                  (("hall-light", "power"), ("fan", "power"), ("camera", "recording"))
                  for value in (True, False)]
        cases += [("door", "lock", True)]
        ids = set()
        for device, action, value in cases:
            with self.subTest(device=device, action=action, value=value):
                count = len(self.published)
                response = await self.client.post(
                    "/api/control", json=self.command(device=device, action=action,
                                                       value=value, confirmed=True),
                    headers={"Origin": "https://dashboard.example"})
                self.assertEqual(response.status, 202, await response.text())
                body = await response.json()
                self.assertIs(body["ok"], True)
                self.assertEqual(body["status"], "requested")
                self.assertIs(body["simulation"], False)
                self.assertEqual(len(self.published), count + 1)
                topic, command = self.published[-1]
                self.assertEqual(topic, rw.topic("iot", device, "cmd"))
                self.assertEqual(body["command"], command)
                self.assertEqual(command["device"], device)
                self.assertEqual(command["action"], action)
                self.assertEqual(command["value"], value)
                self.assertIs(type(command["value"]), type(value))
                self.assertEqual(command["by"], "dashboard")
                self.assertIsInstance(command["id"], str)
                self.assertTrue(command["id"])
                self.assertNotIn(command["id"], ids)
                ids.add(command["id"])
                self.assertIsInstance(command["ts"], (int, float))
                self.assertNotIsInstance(command["ts"], bool)
                self.assertTrue(math.isfinite(command["ts"]))
                if action == "setpoint":
                    self.assertEqual(command["setpoint"], value)
                else:
                    self.assertNotIn("setpoint", command)
                audit = self.db.read_audit()
                self.assertEqual(len(audit), count + 1)
                self.assertEqual(audit[0]["event"], "device_command_requested")
                self.assertEqual(json.loads(audit[0]["detail"]), command)
                self.assertEqual(audit[0]["ip"], "127.0.0.1")

    async def test_transport_false_returns_503_without_success_audit(self):
        self.login()
        self.transport_result = False
        response = await self.client.post("/api/control", json=self.command())
        self.assertEqual(response.status, 503, await response.text())
        self.assertEqual(len(self.published), 1)
        self.assertEqual(self.db.read_audit(), [])

    async def test_transport_exceptions_return_503_without_success_audit(self):
        self.login()
        for error in (OSError("broker disconnected"), RuntimeError("transport closed"),
                      Exception("unexpected publish failure")):
            with self.subTest(error=type(error).__name__):
                self.transport_error = error
                before = len(self.published)
                response = await self.client.post("/api/control", json=self.command())
                self.assertEqual(response.status, 503, await response.text())
                self.assertEqual(len(self.published), before + 1)
                self.assertEqual(self.db.read_audit(), [])

    async def test_concurrent_commands_have_distinct_ids_and_independent_audits(self):
        self.login()
        values = (18, 20, 22, 24, 26, 28)
        responses = await asyncio.gather(*(
            self.client.post("/api/control", json=self.command(value=value))
            for value in values))
        commands = []
        for response in responses:
            self.assertEqual(response.status, 202, await response.text())
            commands.append((await response.json())["command"])
        self.assertEqual(len(self.published), len(values))
        self.assertEqual(len({command["id"] for command in commands}), len(values))
        self.assertCountEqual([command["value"] for command in commands], values)
        self.assertCountEqual([payload for _, payload in self.published], commands)
        audit = self.db.read_audit()
        self.assertEqual(len(audit), len(values))
        self.assertTrue(all(row["event"] == "device_command_requested" for row in audit))
        self.assertCountEqual([json.loads(row["detail"]) for row in audit], commands)
