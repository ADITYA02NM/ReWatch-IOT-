"""Explicit MQTT bridge permissions; telemetry is evidence, never authorization.

This is not a vendor protocol driver. An enrolled device or trusted bridge must
translate action/value commands and publish observed state on the ReWatch bus.
"""
from __future__ import annotations

import json
import math
import os
import re
from pathlib import Path

import rewatch as rw

KINDS = {
    "ac": {"setpoint"}, "thermostat": {"setpoint"}, "camera": {"recording"},
    "door": {"lock"}, "plug": {"power"}, "light": {"power", "brightness"},
    "fan": {"power", "speed"}, "sensor": set(), "generic": set(),
}


def valid_id(value) -> bool:
    return isinstance(value, str) and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}", value) is not None


def number(value) -> bool:
    return type(value) in (int, float) and math.isfinite(value)


class DevicePolicy:
    def __init__(self, config: dict | None = None) -> None:
        if config is None:
            config = {}
        if not isinstance(config, dict) or len(config) > 1024:
            raise ValueError("device configuration must be an object (max 1024 devices)")
        self.devices = {}
        for device, spec in config.items():
            if not valid_id(device) or not isinstance(spec, dict):
                raise ValueError("invalid device configuration")
            kind = spec.get("kind", "generic")
            actions = spec.get("actions", [])
            if not isinstance(kind, str) or kind not in KINDS or spec.get("adapter", "mqtt") != "mqtt":
                raise ValueError("only declared kinds and MQTT bridges are supported")
            if type(spec.get("enabled", False)) is not bool or not isinstance(actions, list):
                raise ValueError("enabled must be boolean and actions must be a list")
            if any(not isinstance(a, str) or a not in KINDS[kind] for a in actions):
                raise ValueError("unsupported device action")
            firmware = spec.get("approved_firmware", "")
            if not isinstance(firmware, str) or len(firmware) > 128:
                raise ValueError("approved_firmware must be a bounded string")
            maximum = spec.get("max_power_w", 2000)
            if not number(maximum) or not 0 < maximum <= 100000:
                raise ValueError("max_power_w must be a finite positive number")
            self.devices[device] = {**spec, "kind": kind, "adapter": "mqtt",
                                    "actions": list(dict.fromkeys(actions)),
                                    "enabled": spec.get("enabled", False)}

    @classmethod
    def from_env(cls) -> DevicePolicy:
        path = os.environ.get("REWATCH_DEVICES_FILE", "")
        if not path:
            return cls()
        # A local operator-owned file, not a URL or a dashboard-supplied path.
        raw = Path(path).read_bytes()
        if len(raw) > 256 * 1024:
            raise ValueError("device configuration too large")
        return cls(json.loads(raw))

    def inventory(self, telemetry: dict) -> list[dict]:
        rows = []
        for device in sorted(set(self.devices) | set(telemetry)):
            if not valid_id(device):
                continue
            spec, tel = self.devices.get(device, {}), telemetry.get(device, {})
            if not isinstance(tel, dict):
                tel = {}
            actions = spec.get("actions", []) if spec.get("enabled") else []
            rows.append({"device": device, "kind": spec.get("kind", str(tel.get("kind", "generic"))[:32]),
                         "room": str(tel.get("room") or spec.get("room") or device)[:96],
                         "ip": str(tel.get("ip") or "")[:64],
                         "firmware": str(tel.get("firmware") or "unknown")[:128],
                         "adapter": spec.get("adapter", "observe-only"), "actions": list(actions),
                         "control": bool(actions), "observed": device in telemetry,
                         "rx": tel.get("rx", 0)})
        return rows

    def command(self, device, action, value, confirmed=False) -> dict:
        if not valid_id(device) or not isinstance(action, str):
            raise ValueError("invalid device or action")
        spec = self.devices.get(device, {})
        if not spec.get("enabled") or action not in spec.get("actions", []):
            raise ValueError("device/action is not explicitly enabled")
        if action in ("setpoint", "brightness", "speed"):
            lo, hi = (16, 30) if action == "setpoint" else (0, 100)
            if not number(value) or not lo <= value <= hi:
                raise ValueError(f"{action} must be a finite number in {lo}..{hi}")
        elif action in ("power", "recording"):
            if type(value) is not bool:
                raise ValueError("boolean value required")
        elif action == "lock":
            if value is not True or confirmed is not True:
                raise ValueError("locking requires explicit confirmation; unlocking is unsupported")
        else:
            raise ValueError("unsupported action")
        payload = {"device": device, "action": action, "value": value,
                   "id": rw.new_id("cmd"), "by": "dashboard", "ts": rw.now()}
        if action == "setpoint":
            payload["setpoint"] = value  # existing WROOM AC protocol
        return payload


class FirmwareMonitor:
    """Reports *claimed version metadata*, not firmware attestation or CVEs."""
    def __init__(self, policy: DevicePolicy) -> None:
        self.policy = policy
        self.versions: dict[str, str] = {}

    def feed(self, tel: dict, t: float) -> list[dict]:
        device, version = tel.get("device"), tel.get("firmware")
        if not valid_id(device) or not isinstance(version, str) or not version:
            return []
        version = version[:128]
        old = self.versions.get(device)
        if old == version:
            return []
        if len(self.versions) >= 1024 and device not in self.versions:
            victim = next((key for key in self.versions if key not in self.policy.devices), None)
            if device not in self.policy.devices or victim is None:
                return []
            del self.versions[victim]
        self.versions[device] = version
        approved = self.policy.devices.get(device, {}).get("approved_firmware")
        if old is None and (not approved or approved == version):
            return []
        ev = rw.make_event("firmware-change", "medium",
                           f"{device}: reported firmware {old or 'unknown'} → {version} (unattested)",
                           device=device, detail={"previous": old, "reported": version,
                                                  "approved": approved, "attested": False})
        ev["ts"] = t
        return [ev]
