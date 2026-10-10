import logging
import os
import random
import time

import requests

API_URL = os.getenv("API_URL", "http://localhost:8000")
INTERVAL_SECONDS = float(os.getenv("INTERVAL_SECONDS", "3"))
# Adım 3'te /health eklenince bu /health olacak
READY_PATH = "/vehicles"

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("simulator")


def wait_for_api(retries=30, delay=2):
    """API ayağa kalkana kadar bekle."""
    for attempt in range(1, retries + 1):
        try:
            if requests.get(f"{API_URL}{READY_PATH}", timeout=3).ok:
                log.info("API hazır: %s", API_URL)
                return
        except requests.RequestException:
            pass
        log.info("API bekleniyor... (%d/%d)", attempt, retries)
        time.sleep(delay)
    raise SystemExit(f"API'ye ulaşılamadı: {API_URL}")


def get_vehicle_ids():
    """Mevcut araçları al, hiç yoksa birkaç tane oluştur."""
    vehicles = requests.get(f"{API_URL}/vehicles", timeout=5).json()
    if not vehicles:
        for name in ["Truck-1", "Truck-2", "Van-1"]:
            requests.post(f"{API_URL}/vehicles", json={"name": name}, timeout=5).raise_for_status()
            log.info("Araç oluşturuldu: %s", name)
        vehicles = requests.get(f"{API_URL}/vehicles", timeout=5).json()
    return [v["id"] for v in vehicles]


def main():
    wait_for_api()
    vehicle_ids = get_vehicle_ids()
    log.info("Simülasyon başladı, araçlar: %s", vehicle_ids)

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
                log.info("Araç %s → sıcaklık: %.1f°C, durum: %s", vid, temp, status)
            except requests.RequestException as e:
                log.error("Araç %s için veri gönderilemedi: %s", vid, e)
        time.sleep(INTERVAL_SECONDS)


if __name__ == "__main__":
    main()
