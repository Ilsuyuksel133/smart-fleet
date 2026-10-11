import random

import pytest

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
