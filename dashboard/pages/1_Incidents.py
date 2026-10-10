"""Incidents: reports written by the AI incident agent."""

import os

import requests
import streamlit as st

AGENT_URL = os.getenv("AGENT_URL", "http://localhost:8100")
ALERTS = ["FleetApiDown", "VehicleOverheating", "HighAlertRate"]
CATEGORY_ICONS = {
    "service_down": "🔴",
    "sensor_anomaly": "🌡️",
    "alert_storm": "🌪️",
    "unknown": "❔",
}

st.title("Incidents")
st.caption(
    "Root cause analysis reports written by the AI incident agent. "
    "The agent only reads metrics, logs and the runbook; every action is up to you."
)


def get(path: str):
    response = requests.get(f"{AGENT_URL}{path}", timeout=5)
    response.raise_for_status()
    return response.json()


# --- Manual trigger ---
with st.expander("Start an investigation manually"):
    alert_name = st.selectbox("Alert", ALERTS)
    if st.button("Investigate"):
        try:
            response = requests.post(
                f"{AGENT_URL}/investigate", json={"alert_name": alert_name}, timeout=5
            )
            if response.status_code == 409:
                st.warning(f"Not started: {response.json()['detail']}")
            else:
                response.raise_for_status()
                st.success(
                    f"Investigation #{response.json()['investigation_id']} queued. "
                    "It usually takes about a minute with a local model."
                )
        except requests.RequestException as e:
            st.error(f"Cannot reach the agent ({AGENT_URL}): {e}")

st.button("Refresh")

# --- Report list ---
try:
    reports = get("/reports")
except requests.RequestException as e:
    st.error(f"Cannot reach the agent ({AGENT_URL}): {e}")
    st.stop()

if not reports:
    st.info("No investigations yet. They start automatically when an alert fires.")
    st.stop()

st.dataframe(
    [
        {
            "#": r["id"],
            "Alert": r["alert_name"],
            "Status": r["status"],
            "Category": f"{CATEGORY_ICONS.get(r['category'], '')} {r['category'] or ''}".strip(),
            "Confidence": r["confidence"] or "",
            "Trigger": r["trigger"],
            "Started (UTC)": r["created_at"][:19].replace("T", " "),
            "Summary": r["summary"] or "",
        }
        for r in reports
    ],
    hide_index=True,
    use_container_width=True,
)

# --- Report detail ---
options = {f"#{r['id']} {r['alert_name']} ({r['status']})": r["id"] for r in reports}
choice = st.selectbox("Show report", list(options))
detail = get(f"/reports/{options[choice]}")
report = detail["report"]

if detail["status"] in ("queued", "running"):
    st.info(f"Investigation is {detail['status']}. Refresh in a moment.")
elif detail["status"] == "failed":
    st.error(f"Investigation failed: {detail['error']}")
else:
    icon = CATEGORY_ICONS.get(report["root_cause_category"], "")
    st.subheader(f"{icon} {report['root_cause_category']} · confidence: {report['confidence']}")
    st.write(report["summary"])

    col1, col2, col3 = st.columns(3)
    col1.metric("Steps", report["steps_used"])
    col2.metric("Duration", f"{report['duration_seconds']:.0f} s")
    col3.metric("Stop reason", report["stop_reason"])

    st.markdown("**Root cause**")
    st.write(report["root_cause_explanation"])

    st.markdown("**Suggested actions** (review before acting)")
    for action in report["suggested_actions"]:
        st.markdown(f"- {action}")

    st.markdown("**Evidence**")
    if report["evidence"]:
        st.dataframe(report["evidence"], hide_index=True, use_container_width=True)
    else:
        st.write("No evidence was collected.")

    with st.expander("Alert"):
        st.json(detail["alert"])
