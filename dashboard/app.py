import os

import requests
import streamlit as st

API_URL = os.getenv("API_URL", "http://localhost:8000")

st.title("Smart Fleet Monitor")

try:
    vehicles = requests.get(f"{API_URL}/vehicles", timeout=5).json()
    alerts = requests.get(f"{API_URL}/alerts", timeout=5).json()
except requests.RequestException as e:
    st.error(f"API'ye ulaşılamıyor ({API_URL}): {e}")
    st.stop()

# Vehicle list
st.header("Araçlar")
if vehicles:
    for v in vehicles:
        st.metric(label=v["name"], value=v["status"])
else:
    st.info("Henüz araç yok.")

# Alerts
st.header("Alertler")
if alerts:
    for a in alerts:
        st.error(f"Araç {a['vehicle_id']} — {a['reason']} ({a['timestamp']})")
else:
    st.success("Aktif alert yok.")
