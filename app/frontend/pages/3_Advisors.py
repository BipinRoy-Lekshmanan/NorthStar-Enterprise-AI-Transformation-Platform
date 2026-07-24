"""Advisors page (Milestone 7) -- browse the 10 domain advisors and ask
one directly, entirely through the platform API. Advisors are
specialized RAG modes (persona + retrieval scope + response structure
over the shared grounded pipeline), not autonomous agents.
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

st.set_page_config(page_title="Advisors", page_icon="\U0001F9ED", layout="wide")
init_session()

st.title("Advisors")
st.caption(
    "Advisors are specialized RAG modes over Northstar's knowledge base -- a persona, a "
    "retrieval scope, and a response structure layered on the same shared grounded pipeline. "
    "They are not autonomous agents: each one answers exactly one question, once, when asked."
)

user = get_current_user()
if user is None:
    st.warning("Enter an API key on the Home page to browse advisors.")
    st.stop()

client = get_api_client()

try:
    advisors = client.list_advisors()
except ApiClientError as exc:
    st.error(f"Could not load advisors: {exc.message}")
    st.stop()

st.markdown(f"**{len(advisors)} advisors available**")

cols = st.columns(2)
for i, advisor in enumerate(advisors):
    with cols[i % 2]:
        with st.container(border=True):
            st.markdown(f"#### {advisor['display_name']}")
            st.caption(advisor["description"])
            st.write("**Relevant domains:** " + ", ".join(advisor["domains"][:5]))
            st.write("**Expected output:** " + " -> ".join(advisor["expected_output_sections"]))
            st.caption(f"Prompt version: `{advisor['prompt_version']}`")

st.markdown("---")
st.markdown("### Ask a specific advisor")

if user["role"] not in ("engineer", "reviewer", "administrator"):
    st.info("Direct advisor queries require the engineer role or higher. Use the Enterprise Assistant page instead.")
else:
    advisor_ids = [a["advisor_id"] for a in advisors]
    selected = st.selectbox("Advisor", advisor_ids)
    question = st.text_area("Question", height=80)
    include_diagnostics = st.checkbox("Show diagnostics", value=False, key="advisor_diagnostics")

    if st.button("Ask advisor", type="primary", disabled=not question.strip()):
        try:
            with st.spinner("Asking..."):
                result = client.query_advisor(selected, question=question, include_diagnostics=include_diagnostics)
        except ApiClientError as exc:
            st.error(f"{exc.code or 'ERROR'}: {exc.message}")
        else:
            if not result["sufficient_context"]:
                st.warning("Insufficient context: the knowledge base did not contain enough evidence.")
            st.markdown("#### Answer")
            st.markdown(result["answer"])
            if result["citations"]:
                st.markdown("#### Sources")
                for i, citation in enumerate(result["citations"], 1):
                    with st.expander(f"{i}. {citation['document_title'] or citation['source_file']}"):
                        st.write(citation["excerpt"])
            if result.get("diagnostics"):
                with st.expander("Diagnostics"):
                    st.json(result["diagnostics"])
