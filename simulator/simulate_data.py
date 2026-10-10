import logging
import os
import random
import time

import requests

from logging_config import setup_logging

API_URL = os.getenv("API_URL", "http://localhost:8000")
INTERVAL_SECONDS = float(os.getenv("INTERVAL_SECONDS", "3"))

setup_logging()
log = logging.getLogger("simulator")


def wait_for_api(retries=30, delay=2):
    """API ayağa kalkana kadar bekle."""
    for attempt in range(1, retries + 1):
        try:
            if requests.get(f"{API_URL}/health", timeout=3).ok:
                log.info("api ready", extra={"api_url": API_URL})
                return
        except requests.RequestException:
            pass
        log.info("waiting for api", extra={"attempt": attempt, "retries": retries})
        time.sleep(delay)
    raise SystemExit(f"API'ye ulaşılamadı: {API_URL}")


def get_vehicle_ids():
    """Mevcut araçları al, hiç yoksa birkaç tane oluştur."""
    vehicles = requests.get(f"{API_URL}/vehicles", timeout=5).json()
    if not vehicles:
        for name in ["Truck-1", "Truck-2", "Van-1"]:
            requests.post(f"{API_URL}/vehicles", json={"name": name}, timeout=5).raise_for_status()
            log.info("vehicle created", extra={"vehicle_name": name})
        vehicles = requests.get(f"{API_URL}/vehicles", timeout=5).json()
    return [v["id"] for v in vehicles]


def main():
    wait_for_api()
    vehicle_ids = get_vehicle_ids()
    log.info("simulation started", extra={"vehicle_ids": vehicle_ids})

    while True:
        for vid in vehicle_ids:
            temp = round(random.uniform(60, 100), 1)
            status = random.choice(["OK", "OK", "OK", "ERROR"])
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
