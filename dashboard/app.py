"""Entry point of the dashboard: defines the pages and their names in the sidebar."""

import streamlit as st

# Wide layout: the incident tables (evidence, findings) need the horizontal space
st.set_page_config(page_title="Smart Fleet", page_icon="🚚", layout="wide")

pages = [
    st.Page("fleet.py", title="Fleet", icon="🚚", default=True),
    st.Page("incidents.py", title="Incidents", icon="🚨", url_path="Incidents"),
]
st.navigation(pages).run()
