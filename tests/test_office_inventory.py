"""Contracts for the simulated smart-office inventory, not real hardware."""

from collections import Counter
from copy import deepcopy
import os
from pathlib import Path
import sys
from unittest.mock import patch

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "demo"))
import demo_server  # noqa: E402

LOCATIONS = {
    "ac": {"Room 1", "Room 2", "Room 3", "Room 4"},
    "camera": {"Reception", "Main Entrance", "Corridor", "Parking"},
    "door": {"Main Entrance", "Meeting Room", "Server Room", "Emergency Exit"},
    "plug": {"Workstations", "Printer Area", "Pantry", "Server Rack"},
    "light": {"Reception", "Open Office", "Meeting Room", "Corridor"},
    "fan": {"Open Office", "Meeting Room", "Pantry", "Utility Room"},
    "sensor": {"Server Room", "Pantry", "Washroom", "Open Office"},
}


@pytest.fixture
def office():
    with patch.dict(os.environ, {"DEMO_AUTO_SPIKE": "0"}), \
            patch.object(demo_server.random, "uniform", return_value=0.0), \
            patch.object(demo_server.random, "random", return_value=1.0):
        sim = demo_server.Sim({"broadcast": lambda frame: None}, False)
        sim.replay(100.0)
        sim.tick(120.0)
        yield sim


def test_office_has_four_devices_at_distinct_locations_per_kind(office):
    assert Counter(t["kind"] for t in office.telemetry.values()) == dict.fromkeys(LOCATIONS, 4)
    for kind, locations in LOCATIONS.items():
        assert {t["room"] for t in office.telemetry.values() if t["kind"] == kind} == locations
    addresses = [t["ip"] for t in office.telemetry.values()]
    assert len(addresses) == len(set(addresses)) == 28
    assert set(office.policy.devices) == set(office.telemetry)


@pytest.mark.parametrize("kind,action,value", [
    ("ac", "setpoint", 22), ("camera", "recording", False),
    ("door", "lock", True), ("plug", "power", False),
    ("light", "brightness", 35), ("fan", "speed", 25),
])
def test_every_office_member_has_independent_simulated_controls(office, kind, action, value):
    members = [dev for dev, tel in office.telemetry.items() if tel["kind"] == kind]
    assert len(members) == 4
    for device in members:
        before = deepcopy(office.telemetry)
        command = office.policy.command(device, action, value, confirmed=True)
        office._on_engine(demo_server.rw.topic("iot", device, "cmd"), command)
        office.tick(121.0)
        assert office.telemetry[device][action] == value
        for other in members:
            if other != device:
                assert office.telemetry[other][action] == before[other][action]


def test_office_sensors_remain_observe_only(office):
    sensors = [dev for dev, tel in office.telemetry.items() if tel["kind"] == "sensor"]
    assert len(sensors) == 4
    for device in sensors:
        assert office.policy.devices[device]["actions"] == []
        with pytest.raises(ValueError):
            office.policy.command(device, "power", False)


def test_office_replay_keeps_inventory_and_immediately_restores_baselines(office):
    ids = set(office.telemetry)
    assert len(ids) == 28
    office.rig("ac-spike", "room2-ac")
    office.extras["lobby-plug"]["power"] = False
    office.extras["entry-camera"]["recording"] = False
    office.tick(121.0)
    office.replay(200.0)
    snapshot = office.snapshot()
    assert set(snapshot["telemetry"]) == ids
    assert snapshot["events"] == snapshot["history"] == []
    assert snapshot["state"]["score"] == 0
    assert snapshot["state"]["incident"] is None
    assert snapshot["telemetry"]["lobby-plug"]["power"] is True
    assert snapshot["telemetry"]["entry-camera"]["recording"] is True
    assert snapshot["telemetry"]["room2-ac"]["power"] == "on"
    office.tick(201.0)
    assert set(office.telemetry) == ids


def test_office_baselines_stay_calm(office):
    assert len(office.telemetry) == 28
    for now in range(121, 241):
        office.tick(float(now))
        assert office.eng.incident is None
        assert office.eng.band == "GREEN"
        assert office.state["score"] < 30
