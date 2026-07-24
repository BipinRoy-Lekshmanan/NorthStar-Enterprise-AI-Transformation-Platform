"""Platform Operations page (Milestone 7) -- detailed health/component
diagnostics and the audit log. Knowledge-base ingestion/indexing/rebuild
live on the Knowledge Explorer page's Administration tab; this page is
read-only operational visibility, not another place to trigger them.
"""

from __future__ import annotations

import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

import streamlit as st

from app.frontend.api_client import ApiClientError
from app.frontend.session import get_api_client, get_current_user, init_session

st.set_page_config(page_title="Platform Operations", page_icon="\U0001F5A5", layout="wide")
init_session()

st.title("Platform Operations")
st.caption("Operational diagnostics -- component health and the audit trail of significant actions.")

user = get_current_user()
if user is None:
    st.warning("Enter an API key on the Home page to view platform operations.")
    st.stop()

client = get_api_client()

st.markdown("### Health")
try:
    health = client.health_detail()
except ApiClientError as exc:
    st.error(f"Could not load health detail: {exc.message}")
else:
    status_cols = st.columns(4)
    status_cols[0].metric("Status", health["status"])
    status_cols[1].metric("Version", health["version"])
    status_cols[2].metric("Uptime (min)", f"{health['uptime_seconds'] / 60:.1f}")
    status_cols[3].metric("Advisors / Workflows", f"{health['advisor_count']} / {health['workflow_count']}")

    st.markdown("**Components**")
    for name, value in health["components"].items():
        icon = "✅" if value == "ok" else "⚠️"
        st.write(f"{icon} {name}: {value}")

st.markdown("---")
st.markdown("### Audit log")

if user["role"] != "administrator":
    st.info("Viewing the audit log requires the administrator role.")
else:
    limit = st.slider("Number of recent events", min_value=10, max_value=200, value=50, step=10)
    try:
        events = client.audit_events(limit=limit)
    except ApiClientError as exc:
        st.error(f"Could not load audit log: {exc.message}")
        events = []

    if not events:
        st.info("No audit events recorded yet.")
    else:
        st.caption(f"Showing {len(events)} most recent event(s), newest first.")
        for event in events:
            with st.container(border=True):
                cols = st.columns(4)
                cols[0].write(f"**{event['action']}**")
                cols[1].write(f"actor: {event['actor']} ({event['role']})")
                cols[2].write(f"{event['resource_type'] or 'n/a'}: {event['resource_id'] or 'n/a'}")
                cols[3].write(event["timestamp"])
                if event["metadata"]:
                    st.json(event["metadata"])
