"""Security and metadata contracts for the pure-Python IoT policy layer."""

import json
import math
from pathlib import Path
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "common"))
from iot import DevicePolicy, FirmwareMonitor  # noqa: E402


def entry(kind="ac", actions=None, **overrides):
    """Return a fresh, explicitly authorized configuration for each test."""
    defaults = {
        "ac": ["setpoint"],
        "thermostat": ["setpoint"],
        "plug": ["power"],
        "light": ["power", "brightness"],
        "fan": ["power", "speed"],
        "camera": ["recording"],
        "door": ["lock"],
        "sensor": [],
        "generic": [],
    }
    return {
        "kind": kind,
        "adapter": "mqtt",
        "enabled": True,
        "actions": list(defaults[kind] if actions is None else actions),
        **overrides,
    }


def observed(device="room1-ac", firmware="1.0", **overrides):
    return {
        "device": device,
        "kind": "ac",
        "room": "Room 1",
        "ip": "192.0.2.10",
        "firmware": firmware,
        **overrides,
    }


@pytest.mark.parametrize("config", [None, {}])
def test_unconfigured_devices_are_visible_but_never_controllable(config):
    policy = DevicePolicy(config)
    rows = policy.inventory({"room1-ac": observed()})
    assert len(rows) == 1
    row = rows[0]
    assert row["device"] == "room1-ac"
    assert row["observed"] is True
    assert row["control"] is False
    assert row["actions"] == []
    with pytest.raises(ValueError):
        policy.command("room1-ac", "setpoint", 20)


def test_inventory_contains_required_metadata_and_unobserved_configured_devices():
    policy = DevicePolicy({"room1-ac": entry(), "hall-light": entry("light")})
    rows = {row["device"]: row for row in policy.inventory({"room1-ac": observed()})}
    assert set(rows) == {"room1-ac", "hall-light"}
    required = {"device", "kind", "room", "ip", "firmware", "actions", "control", "adapter", "observed"}
    assert all(required <= row.keys() for row in rows.values())
    ac = rows["room1-ac"]
    assert ac["kind"] == "ac"
    assert ac["room"] == "Room 1"
    assert ac["ip"] == "192.0.2.10"
    assert ac["firmware"] == "1.0"
    assert ac["actions"] == ["setpoint"]
    assert ac["control"] is True
    assert ac["adapter"] == "mqtt"
    assert ac["observed"] is True
    assert rows["hall-light"]["observed"] is False


def test_empty_inventory_without_configuration():
    assert DevicePolicy().inventory({}) == []


def test_telemetry_cannot_grant_permissions_or_override_configured_kind():
    policy = DevicePolicy({"room1-ac": entry(actions=[])})
    tel = observed(kind="door", actions=["unlock", "setpoint"], enabled=True,
                   control=True, adapter="mqtt")
    row = policy.inventory({"room1-ac": tel})[0]
    assert row["kind"] == "ac"
    assert row["actions"] == []
    assert row["control"] is False
    for action, value in [("unlock", True), ("setpoint", 20)]:
        with pytest.raises(ValueError):
            policy.command("room1-ac", action, value, confirmed=True)


@pytest.mark.parametrize("kind", ["camera", "door", "plug", "ac", "light", "fan", "sensor", "thermostat", "generic"])
def test_inventory_supports_each_declared_kind(kind):
    policy = DevicePolicy({"device-1": entry(kind)})
    row = policy.inventory({})[0]
    assert row["device"] == "device-1"
    assert row["kind"] == kind
    assert set(row["actions"]) == set(entry(kind)["actions"])


@pytest.mark.parametrize("config", [
    [], "all", True, 1,
    {"device": None}, {"device": []}, {"device": "mqtt"},
    {"device": entry(kind="ac", adapter="http")},
    {"device": entry(enabled="true")},
    {"device": entry(enabled=1)},
    {"device": {**entry(), "kind": "unknown"}},
    {"device": entry(actions="setpoint")},
    {"device": {**entry(), "actions": None}},
    {"device": entry(actions=[None])},
    {"device": entry(actions=["reboot"])},
    {"device": entry(approved_firmware=123)},
    {"device": entry(max_power_w="100")},
    {"device": entry(max_power_w=True)},
    {"device": entry(max_power_w=float("nan"))},
    {"device": entry(max_power_w=float("inf"))},
])
def test_invalid_configuration_fails_closed(config):
    with pytest.raises(ValueError):
        DevicePolicy(config)


@pytest.mark.parametrize("device", ["", "../door", "a/b", "a\\b", "+", "#", "room+", "room#", "-ac", "_ac", "ac room", "é-ac", "ac\n", "a" * 65])
def test_unsafe_mqtt_identifiers_rejected_in_configuration_and_commands(device):
    with pytest.raises(ValueError):
        DevicePolicy({device: entry()})
    with pytest.raises(ValueError):
        DevicePolicy({"room1-ac": entry()}).command(device, "setpoint", 20)


@pytest.mark.parametrize("device", ["a", "A", "0", "room1-ac", "Room_2", "a" * 64])
def test_safe_mqtt_identifiers_accepted(device):
    policy = DevicePolicy({device: entry()})
    assert policy.command(device, "setpoint", 20)["device"] == device


@pytest.mark.parametrize("device", [None, True, 12, [], {}])
def test_non_string_command_device_is_rejected(device):
    with pytest.raises(ValueError):
        DevicePolicy({"room1-ac": entry()}).command(device, "setpoint", 20)


@pytest.mark.parametrize("config,device", [
    ({}, "unknown"),
    ({"room1-ac": entry()}, "unknown"),
    ({"room1-ac": entry(enabled=False)}, "room1-ac"),
    ({"room1-ac": entry(actions=[])}, "room1-ac"),
])
def test_control_requires_explicit_enabled_device_and_action(config, device):
    with pytest.raises(ValueError):
        DevicePolicy(config).command(device, "setpoint", 20)


@pytest.mark.parametrize("kind,action,value", [
    ("ac", "setpoint", 16), ("ac", "setpoint", 30),
    ("ac", "setpoint", 22.5), ("thermostat", "setpoint", 21),
    ("plug", "power", True), ("plug", "power", False),
    ("light", "power", True), ("fan", "power", False),
    ("light", "brightness", 0), ("light", "brightness", 100),
    ("light", "brightness", 42.5),
    ("fan", "speed", 0), ("fan", "speed", 100), ("fan", "speed", 25.5),
    ("camera", "recording", True), ("camera", "recording", False),
    ("door", "lock", True),
])
def test_valid_commands_return_bridge_envelope(kind, action, value):
    policy = DevicePolicy({"device-1": entry(kind)})
    command = policy.command("device-1", action, value, confirmed=kind == "door")
    assert command["device"] == "device-1"
    assert command["action"] == action
    assert command["value"] == value
    assert type(command["value"]) is type(value)
    assert command["by"] == "dashboard"
    assert isinstance(command["id"], str) and command["id"]
    assert isinstance(command["ts"], (int, float)) and not isinstance(command["ts"], bool)
    assert math.isfinite(command["ts"])
    if action == "setpoint":
        assert command["setpoint"] == value
    json.dumps(command, allow_nan=False)


def test_commands_have_distinct_ids():
    policy = DevicePolicy({"room1-ac": entry()})
    ids = [policy.command("room1-ac", "setpoint", 20)["id"] for _ in range(100)]
    assert len(set(ids)) == 100


@pytest.mark.parametrize("kind,action", [("ac", "setpoint"), ("thermostat", "setpoint"), ("light", "brightness"), ("fan", "speed")])
@pytest.mark.parametrize("value", [None, True, False, "20", [], {}, float("nan"), float("inf"), -float("inf")])
def test_numeric_actions_reject_nonfinite_boolean_and_non_numeric_values(kind, action, value):
    with pytest.raises(ValueError):
        DevicePolicy({"device-1": entry(kind)}).command("device-1", action, value)


@pytest.mark.parametrize("kind,action,value", [
    ("ac", "setpoint", 15.999), ("ac", "setpoint", 30.001),
    ("thermostat", "setpoint", 15), ("thermostat", "setpoint", 31),
    ("light", "brightness", -0.01), ("light", "brightness", 100.01),
    ("fan", "speed", -1), ("fan", "speed", 101),
])
def test_numeric_actions_reject_out_of_range_values(kind, action, value):
    with pytest.raises(ValueError):
        DevicePolicy({"device-1": entry(kind)}).command("device-1", action, value)


@pytest.mark.parametrize("kind,action", [("plug", "power"), ("light", "power"), ("fan", "power"), ("camera", "recording")])
@pytest.mark.parametrize("value", [None, 0, 1, "true", "false", [], {}])
def test_boolean_actions_require_actual_booleans(kind, action, value):
    with pytest.raises(ValueError):
        DevicePolicy({"device-1": entry(kind)}).command("device-1", action, value)


@pytest.mark.parametrize("value,confirmed", [
    (True, False), (False, True), (1, True), ("true", True),
    (None, True), (True, 1), (True, "true"), (True, None),
])
def test_door_lock_requires_literal_true_and_explicit_boolean_confirmation(value, confirmed):
    with pytest.raises(ValueError):
        DevicePolicy({"door": entry("door")}).command("door", "lock", value, confirmed=confirmed)


@pytest.mark.parametrize("value", [True, False, None])
def test_door_unlock_is_always_rejected(value):
    policy = DevicePolicy({"door": entry("door")})
    with pytest.raises(ValueError):
        policy.command("door", "unlock", value, confirmed=True)


@pytest.mark.parametrize("kind,action,value", [
    ("ac", "power", True), ("plug", "setpoint", 20),
    ("camera", "unlock", True), ("door", "recording", True),
    ("light", "speed", 50), ("fan", "brightness", 50),
    ("sensor", "power", True), ("generic", "power", True),
    ("ac", "reboot", True), ("ac", "", 20),
    ("ac", None, 20), ("ac", [], 20),
])
def test_unsupported_actions_fail_closed(kind, action, value):
    with pytest.raises(ValueError):
        DevicePolicy({"device-1": entry(kind)}).command("device-1", action, value, confirmed=True)


def test_firmware_first_unapproved_baseline_is_not_an_alert():
    monitor = FirmwareMonitor(DevicePolicy())
    assert monitor.feed(observed(), 100.0) == []
    assert monitor.feed(observed(), 101.0) == []


def test_firmware_approved_baseline_is_not_an_alert():
    monitor = FirmwareMonitor(DevicePolicy({"room1-ac": entry(approved_firmware="1.0")}))
    assert monitor.feed(observed(), 100.0) == []


def test_initial_approved_version_mismatch_emits_once():
    monitor = FirmwareMonitor(DevicePolicy({"room1-ac": entry(approved_firmware="2.0")}))
    events = monitor.feed(observed(), 100.0)
    assert len(events) == 1
    assert events[0]["kind"] == "firmware-change"
    assert events[0]["device"] == "room1-ac"
    assert monitor.feed(observed(), 101.0) == []


@pytest.mark.parametrize("config", [None, {"room1-ac": entry()}])
def test_firmware_change_detected_even_for_unconfigured_devices_and_deduplicated(config):
    monitor = FirmwareMonitor(DevicePolicy(config))
    assert monitor.feed(observed(firmware="1.0"), 100.0) == []
    changed = monitor.feed(observed(firmware="2.0"), 101.0)
    assert len(changed) == 1
    assert changed[0]["kind"] == "firmware-change"
    assert changed[0]["device"] == "room1-ac"
    assert "2.0" in json.dumps(changed[0])
    assert monitor.feed(observed(firmware="2.0"), 102.0) == []
    assert len(monitor.feed(observed(firmware="1.0"), 103.0)) == 1


def test_firmware_baselines_are_isolated_by_device():
    monitor = FirmwareMonitor(DevicePolicy())
    assert monitor.feed(observed("ac-a", "1.0"), 100.0) == []
    assert monitor.feed(observed("ac-b", "2.0"), 100.0) == []
    assert monitor.feed(observed("ac-a", "1.0"), 101.0) == []
    events = monitor.feed(observed("ac-b", "3.0"), 101.0)
    assert len(events) == 1
    assert events[0]["device"] == "ac-b"


def test_room_ip_and_kind_changes_do_not_count_as_firmware_changes():
    monitor = FirmwareMonitor(DevicePolicy())
    assert monitor.feed(observed(), 100.0) == []
    assert monitor.feed(observed(room="Elsewhere", ip="192.0.2.99", kind="sensor"), 101.0) == []


def test_firmware_events_are_version_metadata_not_cryptographic_verification():
    monitor = FirmwareMonitor(DevicePolicy({"room1-ac": entry(approved_firmware="1.0")}))
    assert monitor.feed(observed(), 100.0) == []
    events = monitor.feed(observed(firmware="2.0", verified=True, signature_verified=True), 101.0)
    assert len(events) == 1
    event = events[0]
    assert event["kind"] == "firmware-change"
    for field in ("verified", "signature_verified", "integrity_verified"):
        assert event.get(field) is not True


def test_untrusted_long_firmware_metadata_is_bounded_and_repeat_is_silent():
    monitor = FirmwareMonitor(DevicePolicy())
    assert monitor.feed(observed(firmware="1.0"), 100.0) == []
    version = "untrusted-😀-'\";--" * 10_000
    events = monitor.feed(observed(firmware=version), 101.0)
    assert len(events) == 1
    assert events[0]["kind"] == "firmware-change"

    def strings(value):
        if isinstance(value, str):
            yield value
        elif isinstance(value, dict):
            for item in value.values():
                yield from strings(item)
        elif isinstance(value, list):
            for item in value:
                yield from strings(item)

    assert all(len(text) < len(version) for text in strings(events[0]))
    assert monitor.feed(observed(firmware=version), 102.0) == []
