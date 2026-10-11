import logging
import os
import random
import time

import requests

from logging_config import setup_logging

API_URL = os.getenv("API_URL", "http://localhost:8000")
INTERVAL_SECONDS = float(os.getenv("INTERVAL_SECONDS", "3"))
# Fault modes for the agent evaluation (eval/). "random" is the normal behaviour.
#   random:   60-100 °C, 25 % ERROR status (keeps alerts firing, good for demos)
#   calm:     60-78 °C, always OK (no alerts; clean baseline)
#   overheat: like calm, but the first vehicle reports 95-100 °C
#   storm:    calm temperatures, but every vehicle reports ERROR (many alerts)
SIMULATOR_MODE = os.getenv("SIMULATOR_MODE", "random")
MODES = ("random", "calm", "overheat", "storm")

setup_logging()
log = logging.getLogger("simulator")


def wait_for_api(retries=30, delay=2):
    """Wait until the API is up."""
    for attempt in range(1, retries + 1):
        try:
            if requests.get(f"{API_URL}/health", timeout=3).ok:
                log.info("api ready", extra={"api_url": API_URL})
                return
        except requests.RequestException:
            pass
        log.info("waiting for api", extra={"attempt": attempt, "retries": retries})
        time.sleep(delay)
    raise SystemExit(f"API not reachable: {API_URL}")


SIMULATED_VEHICLES = ["Truck-1", "Truck-2", "Van-1"]


def get_vehicle_ids():
    """Return all vehicle IDs, first creating any of our own vehicles that are missing.

    Checking by name (instead of "only if there are no vehicles at all") avoids a
    race: if another client, e.g. the smoke test, creates a vehicle first, the
    simulator still gets its full fleet.
    """
    existing = {v["name"] for v in requests.get(f"{API_URL}/vehicles", timeout=5).json()}
    for name in SIMULATED_VEHICLES:
        if name not in existing:
            requests.post(f"{API_URL}/vehicles", json={"name": name}, timeout=5).raise_for_status()
            log.info("vehicle created", extra={"vehicle_name": name})
    vehicles = requests.get(f"{API_URL}/vehicles", timeout=5).json()
    return [v["id"] for v in vehicles]


def generate_reading(mode: str, index: int) -> tuple[float, str]:
    """Temperature and status for the vehicle at position `index` in the list."""
    if mode == "random":
        return round(random.uniform(60, 100), 1), random.choice(["OK", "OK", "OK", "ERROR"])
    calm_temperature = round(random.uniform(60, 78), 1)
    if mode == "overheat" and index == 0:
        return round(random.uniform(95, 100), 1), "OK"
    if mode == "storm":
        return calm_temperature, "ERROR"
    return calm_temperature, "OK"


def main():
    if SIMULATOR_MODE not in MODES:
        raise SystemExit(f"Unknown SIMULATOR_MODE {SIMULATOR_MODE!r}, expected one of {MODES}")
    wait_for_api()
    vehicle_ids = get_vehicle_ids()
    log.info("simulation started", extra={"vehicle_ids": vehicle_ids, "mode": SIMULATOR_MODE})

    while True:
        for index, vid in enumerate(vehicle_ids):
            temp, status = generate_reading(SIMULATOR_MODE, index)
            try:
                requests.post(
                    f"{API_URL}/vehicles/{vid}/data",
                    json={"temperature": temp, "status": status},
                    timeout=5,
                ).raise_for_status()
                log.info(
                    "reading sent",
                    extra={"vehicle_id": vid, "temperature": temp, "vehicle_status": status},
                )
            except requests.RequestException as e:
                log.error("reading failed", extra={"vehicle_id": vid, "error": str(e)})
        time.sleep(INTERVAL_SECONDS)


if __name__ == "__main__":
    main()
