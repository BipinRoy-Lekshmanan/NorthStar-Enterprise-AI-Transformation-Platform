"""Enterprise Assistant page (Milestone 7) -- grounded Q&A with manual
advisor selection or automatic routing, entirely through the platform
API (`app.frontend.api_client`). No model-provider or retrieval logic
lives here.
"""

from __future__ import annotations

import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

import streamlit as st

from app.frontend.api_client import ApiClientError
from app.frontend.session import add_question_to_history, get_api_client, get_current_user, init_session

st.set_page_config(page_title="Enterprise Assistant", page_icon="\U0001F4AC", layout="wide")
init_session()

st.title("Enterprise Assistant")
st.caption("Specialized RAG modes over Northstar's knowledge base -- not autonomous agents.")

user = get_current_user()
if user is None:
    st.warning("Enter an API key on the Home page to use the Enterprise Assistant.")
    st.stop()

question = st.text_area("Ask a question", height=100, key="assistant_question")

col1, col2 = st.columns(2)
with col1:
    mode = st.radio("Advisor selection", ["Automatic routing", "Manual advisor"], horizontal=True)
with col2:
    advisor_id = None
    if mode == "Manual advisor":
        advisor_id = st.text_input("Advisor id (e.g. 'testing', 'security', 'release')")

include_diagnostics = st.checkbox("Show diagnostics", value=False)

if st.button("Ask", type="primary", disabled=not question.strip()):
    client = get_api_client()
    payload = {
        "question": question,
        "advisor": advisor_id if (mode == "Manual advisor" and advisor_id) else "auto",
        "include_diagnostics": include_diagnostics,
    }
    try:
        with st.spinner("Asking..."):
            result = client.ask_query(**payload)
    except ApiClientError as exc:
        st.error(f"{exc.code or 'ERROR'}: {exc.message}")
    else:
        add_question_to_history(question)

        if not result["sufficient_context"]:
            st.warning(
                "Insufficient context: the Northstar knowledge base did not contain enough "
                "evidence to answer this reliably."
            )

        st.markdown("### Answer")
        st.markdown(result["answer"])

        if result.get("routing"):
            routing = result["routing"]
            with st.expander("Routing", expanded=True):
                st.write(f"Primary advisor: **{routing['primary_advisor']}**")
                if routing["supporting_advisors"]:
                    st.write(f"Supporting advisors: {', '.join(routing['supporting_advisors'])}")
                st.write(f"Confidence: {routing['confidence']:.2f}")
                st.write(f"Rationale: {routing['rationale']}")
                if routing["fallback_used"]:
                    st.warning("Low-confidence fallback -- treat this routing decision cautiously.")

        if result["citations"]:
            st.markdown("### Sources")
            for i, citation in enumerate(result["citations"], 1):
                label = f"{i}. {citation['document_title'] or citation['source_file']} -- {citation['section_title'] or '(no section)'}"
                with st.expander(label):
                    st.write(f"File: `{citation['source_file']}`")
                    st.write(f"Relevance score: {citation['score']:.2f}")
                    st.write(citation["excerpt"])

        if result["warnings"]:
            st.markdown("### Warnings")
            for warning in result["warnings"]:
                st.warning(warning)

        if result["conflicts"]:
            st.markdown("### Conflicts")
            for conflict in result["conflicts"]:
                st.error(conflict)

        if result.get("diagnostics"):
            with st.expander("Diagnostics"):
                st.json(result["diagnostics"])

st.markdown("---")
st.markdown("#### Example questions by category")
examples_by_category = {
    "Architecture": "What architecture principles apply to synchronous service dependencies?",
    "AI Engineering": "What controls are required before deploying AI-generated code?",
    "Security": "What security controls are required for AI systems?",
    "Testing": "What testing evidence is required before release?",
    "Release": "What should happen after a failed canary deployment?",
    "Incident": "How should a Sev-1 incident be handled?",
    "Platform Engineering": "What does the developer portal provide?",
    "Developer Experience": "What onboarding support is provided to new engineers?",
    "Executive Transformation": "How should Northstar prioritize AI transformation investments?",
}
for category, example in examples_by_category.items():
    st.caption(f"**{category}**: {example}")
