"""About page (Milestone 7) -- what this platform is, what it
deliberately does not do, and the milestone history behind it. Static
content; no API key required to view it.
"""

from __future__ import annotations

import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

import streamlit as st

from app.frontend.session import init_session

st.set_page_config(page_title="About", page_icon="ℹ️", layout="wide")
init_session()

st.title("About the HAIE Platform")

st.info(
    "The HAIE Platform is the reference implementation of Human-AI Enterprise Engineering. "
    "Northstar Lending Corporation is a fictional reference enterprise used to demonstrate it "
    "end to end -- knowledge ingestion through grounded Q&A, advisor routing, "
    "human-checkpointed workflows, and evaluation -- not a production system, and it does not "
    "connect to any real company's data."
)

st.markdown("### What this platform does")
st.markdown(
    "- Enterprise knowledge search and grounded, citation-backed Q&A over an internal knowledge base\n"
    "- Manual and automatic selection among 10 domain advisors, with bounded multi-advisor synthesis\n"
    "- 5 human-checkpointed enterprise review workflows (Architecture, AI Solution, Production "
    "Readiness, Incident, Executive AI Transformation Assessment)\n"
    "- Deterministic evaluation of the retrieval, grounding, and workflow layers\n"
    "- Local role-based access control (viewer / engineer / reviewer / administrator)\n"
    "- A full audit trail of significant actions"
)

st.markdown("### What this platform deliberately does not do")
st.markdown(
    "- No autonomous agents, recursive planning, or unrestricted tool use\n"
    "- No shell execution, production deployment actions, or infrastructure modification\n"
    "- No email/ticket creation, browser automation, or writes to external systems\n"
    "- No full SSO/OAuth/SAML/LDAP -- authentication is a local, config-based API key directory\n"
    "- Every workflow pauses for a human decision before any consequential recommendation is finalized"
)

st.markdown("### How it's built")
st.markdown(
    "A FastAPI backend (`app/api/`) exposes every capability through typed, versioned, role-checked "
    "endpoints; a Streamlit frontend (`app/frontend/`) is the only consumer of that API. Neither layer "
    "re-implements retrieval, prompting, routing, or workflow logic -- both are thin wrappers over the "
    "same ingestion, retrieval, RAG, advisor, routing, and workflow modules built in earlier milestones."
)

st.markdown("### Milestone history")
st.markdown(
    "1. Knowledge ingestion foundation\n"
    "2. Semantic indexing and retrieval\n"
    "3. Grounded RAG assistant\n"
    "4. Pluggable advisor framework (10 domain advisors)\n"
    "5. Advisor router and controlled multi-advisor synthesis\n"
    "6. Enterprise workflow orchestration (5 workflows, human checkpoints)\n"
    "7. This platform: an API and web interface over everything above"
)
