import random

import pytest

from simulator import simulate_data
from simulator.simulate_data import MODES, generate_reading


@pytest.fixture(autouse=True)
def fixed_seed():
    random.seed(42)


def readings(mode, index, n=200):
    return [generate_reading(mode, index) for _ in range(n)]


def test_random_mode_keeps_the_original_behaviour():
    values = readings("random", 0)
    assert all(60 <= t <= 100 for t, _ in values)
    statuses = {s for _, s in values}
    assert statuses == {"OK", "ERROR"}


def test_calm_mode_never_triggers_alerts():
    for index in range(3):
        assert all(60 <= t <= 78 and s == "OK" for t, s in readings("calm", index))


def test_overheat_mode_only_affects_the_first_vehicle():
    assert all(t >= 95 and s == "OK" for t, s in readings("overheat", 0))
    assert all(t <= 78 and s == "OK" for t, s in readings("overheat", 1))


def test_storm_mode_reports_errors_without_overheating():
    for index in range(3):
        assert all(t <= 78 and s == "ERROR" for t, s in readings("storm", index))


def test_modes_list():
    assert MODES == ("random", "calm", "overheat", "storm")


class FakeApi:
    """Minimal stand-in for the fleet API's /vehicles endpoint."""

    def __init__(self, names):
        self.vehicles = [{"id": i + 1, "name": n} for i, n in enumerate(names)]

    def get(self, url, timeout):
        return FakeResponse(list(self.vehicles))

    def post(self, url, json, timeout):
        self.vehicles.append({"id": len(self.vehicles) + 1, "name": json["name"]})
        return FakeResponse({})


class FakeResponse:
    def __init__(self, data):
        self.data = data

    def json(self):
        return self.data

    def raise_for_status(self):
        pass


def test_simulator_creates_its_vehicles_even_if_others_exist(monkeypatch):
    # Another client (e.g. the smoke test) created a vehicle before the simulator started
    api = FakeApi(["smoke-test"])
    monkeypatch.setattr(simulate_data.requests, "get", api.get)
    monkeypatch.setattr(simulate_data.requests, "post", api.post)

    assert simulate_data.get_vehicle_ids() == [1, 2, 3, 4]
    assert [v["name"] for v in api.vehicles] == ["smoke-test", "Truck-1", "Truck-2", "Van-1"]


def test_simulator_does_not_duplicate_existing_vehicles(monkeypatch):
    api = FakeApi(["Truck-1", "Truck-2", "Van-1"])
    monkeypatch.setattr(simulate_data.requests, "get", api.get)
    monkeypatch.setattr(simulate_data.requests, "post", api.post)

    assert simulate_data.get_vehicle_ids() == [1, 2, 3]
