"""Approvals page (Milestone 7) -- the reviewer's queue of workflow
executions paused for human approval. A comment is required to reject
or request changes (enforced server-side too); approving resumes the
execution to completion through the same engine the Workflows page
uses to execute it in the first place.
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

st.set_page_config(page_title="Approvals", page_icon="✅", layout="wide")
init_session()

st.title("Approvals")
st.caption(
    "Workflow executions paused for human approval. Rejecting or requesting changes requires a "
    "comment so the requester knows what to address."
)

user = get_current_user()
if user is None:
    st.warning("Enter an API key on the Home page to view approvals.")
    st.stop()

client = get_api_client()

try:
    pending = client.list_pending_approvals()
except ApiClientError as exc:
    st.error(f"Could not load pending approvals: {exc.message}")
    st.stop()

if not pending:
    st.info("Nothing is currently awaiting approval.")
    st.stop()

st.markdown(f"**{len(pending)} execution(s) awaiting approval**")

for item in pending:
    with st.container(border=True):
        st.markdown(f"#### {item['workflow_id']} (v{item['workflow_version']})")
        meta_cols = st.columns(3)
        meta_cols[0].caption(f"Execution: `{item['execution_id']}`")
        meta_cols[1].caption(f"Stage: {item['current_stage'] or 'n/a'}")
        meta_cols[2].caption(f"Started: {item['started_at']}")
        st.write(f"Findings so far: {item['findings_count']} -- Evidence gaps: {item['evidence_gaps_count']}")

        if user["role"] not in ("reviewer", "administrator"):
            st.info("Recording an approval decision requires the reviewer role or higher.")
            continue

        with st.form(key=f"approval_form_{item['execution_id']}"):
            decision = st.radio(
                "Decision", ["approve", "request_changes", "reject", "cancel"],
                horizontal=True, key=f"decision_{item['execution_id']}",
            )
            comments = st.text_area(
                "Comments (required for request_changes / reject)", key=f"comments_{item['execution_id']}",
            )
            submitted = st.form_submit_button("Submit decision", type="primary")

        if submitted:
            try:
                result = client.decide_approval(item["execution_id"], decision, comments=comments or None)
            except ApiClientError as exc:
                st.error(f"{exc.code or 'ERROR'}: {exc.message}")
            else:
                st.success(f"Decision recorded -- execution status is now: {result['status']}")
                st.rerun()
