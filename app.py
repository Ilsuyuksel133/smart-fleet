import streamlit as st
import requests

st.title("Smart Fleet Monitor")

# Araç listesi
st.header("Araçlar")
vehicles = requests.get("http://127.0.0.1:8000/vehicles").json()
if vehicles:
    for v in vehicles:
        st.metric(label=v["name"], value=v["status"])
else:
    st.info("Henüz araç yok.")

# Alertler
st.header("Alertler")
alerts = requests.get("http://127.0.0.1:8000/alerts").json()
if alerts:
    for a in alerts:
        st.error(f"Araç {a['vehicle_id']} — {a['reason']} ({a['timestamp']})")
else:
    st.success("Aktif alert yok.")