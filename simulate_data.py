import requests
import random
import time

vehicles = [1, 2]

print("Simülasyon başladı... (durdurmak için Ctrl+C)")

while True:
    for vid in vehicles:
        temp = random.uniform(60, 100)
        status = random.choice(["OK", "OK", "OK", "ERROR"])
        
        requests.post(f"http://127.0.0.1:8000/vehicles/{vid}/data", json={
            "temperature": round(temp, 1),
            "status": status
        })
        
        print(f"Araç {vid} → sıcaklık: {temp:.1f}°C, durum: {status}")
    
    time.sleep(3)