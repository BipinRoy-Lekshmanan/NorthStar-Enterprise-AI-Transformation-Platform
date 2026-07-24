"""Home page -- the Streamlit entry script (Milestone 7).

Streamlit's own multipage convention makes whichever script is passed to
`streamlit run` the first/default page; the remaining pages live in
`app/frontend/pages/`. This page (and every other page) only ever talks
to the backend through `app.frontend.api_client.ApiClient` -- no
database, vector-store, or model-provider calls happen here.
"""

from __future__ import annotations

import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

import streamlit as st

from app.frontend.api_client import ApiClientError
from app.frontend.session import get_api_client, get_current_user, init_session, set_api_key

st.set_page_config(page_title="Northstar Enterprise AI Platform", page_icon="\U0001F3E6", layout="wide")

init_session()

st.title("Northstar Enterprise AI Transformation Platform")
st.caption(
    "Portfolio reference implementation. Northstar Lending Corporation is a fictional company -- "
    "this platform is not connected to any real enterprise system."
)

st.markdown(
    "The platform provides grounded engineering and AI-transformation guidance using Northstar "
    "Lending Corporation's internal standards, architecture documents, playbooks, and governance "
    "materials. It is **human-controlled and non-autonomous** -- it never executes production "
    "actions, deployments, or infrastructure changes."
)

with st.sidebar:
    st.subheader("Connection")
    base_url = st.text_input("API base URL", value=st.session_state["api_base_url"])
    st.session_state["api_base_url"] = base_url

    api_key_input = st.text_input("API key", value=st.session_state["api_key"], type="password")
    if api_key_input != st.session_state["api_key"]:
        set_api_key(api_key_input)

    user = get_current_user()
    if user:
        st.success(f"Signed in as **{user['username']}** ({user['role']})")
    elif st.session_state["api_key"]:
        st.error("API key not recognized.")
    else:
        st.info("Enter an API key to sign in.")

st.subheader("Platform status")
client = get_api_client()
try:
    health = client.health()
    st.success(f"API status: {health.get('status', 'unknown')}")
except ApiClientError as exc:
    st.error(f"Could not reach the API: {exc.message}")
    st.caption("Start it with: `python -m app.api`")

st.subheader("Quick-start questions")
st.caption("Try these on the Enterprise Assistant page:")
for question in [
    "What controls are required before deploying AI-generated code?",
    "What testing evidence is required before release?",
    "How should a Sev-1 incident be handled?",
]:
    st.markdown(f"- {question}")
