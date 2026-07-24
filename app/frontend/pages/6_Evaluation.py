"""Evaluation page (Milestone 7) -- trigger a grounded-RAG or workflow
evaluation run and browse run history. Deterministic checks only, run
against whichever KB/vector store/workflow store the API server is
currently configured with -- no LLM-as-judge, matching
`app.evaluation.rag_evaluator`/`app.evaluation.workflow_evaluator`.
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

st.set_page_config(page_title="Evaluation", page_icon="\U0001F4CA", layout="wide")
init_session()

st.title("Evaluation")
st.caption(
    "Deterministic evaluation of the grounded-RAG pipeline and the workflow engine against small "
    "seed datasets -- retrieval quality, citation presence, workflow completion, and approval-checkpoint "
    "accuracy. No LLM-as-judge."
)

user = get_current_user()
if user is None:
    st.warning("Enter an API key on the Home page to view evaluation results.")
    st.stop()

client = get_api_client()

can_run = user["role"] in ("engineer", "reviewer", "administrator")

if not can_run:
    st.info("Triggering an evaluation run requires the engineer role or higher.")
else:
    run_cols = st.columns(2)
    if run_cols[0].button("Run grounded-RAG evaluation (Milestone 3 dataset)", type="primary"):
        try:
            with st.spinner("Running evaluation..."):
                result = client.run_evaluation("rag")
        except ApiClientError as exc:
            st.error(f"{exc.code or 'ERROR'}: {exc.message}")
        else:
            st.success(f"Run {result['run_id']} complete -- {result['passed_cases']}/{result['total_cases']} passed.")
    if run_cols[1].button("Run workflow evaluation (Milestone 6 dataset)", type="primary"):
        try:
            with st.spinner("Running evaluation..."):
                result = client.run_evaluation("workflows")
        except ApiClientError as exc:
            st.error(f"{exc.code or 'ERROR'}: {exc.message}")
        else:
            st.success(f"Run {result['run_id']} complete -- {result['passed_cases']}/{result['total_cases']} passed.")

st.markdown("---")
st.markdown("### Run history")

category_filter = st.selectbox("Filter by category", ["(all)", "rag", "workflows"])
try:
    history = client.list_evaluation_runs(category=None if category_filter == "(all)" else category_filter)
except ApiClientError as exc:
    st.error(f"Could not load run history: {exc.message}")
    history = {"items": []}

if not history["items"]:
    st.info("No evaluation runs yet.")
else:
    run_ids = [r["run_id"] for r in history["items"]]
    selected_run_id = st.selectbox(
        "Run",
        run_ids,
        format_func=lambda rid: next(
            f"{r['category']} -- {r['passed_cases']}/{r['total_cases']} passed -- {r['started_at']}"
            for r in history["items"] if r["run_id"] == rid
        ),
    )

    try:
        run = client.get_evaluation_run(selected_run_id)
    except ApiClientError as exc:
        st.error(f"Could not load run detail: {exc.message}")
        run = None

    if run is not None:
        metric_cols = st.columns(3)
        metric_cols[0].metric("Category", run["category"])
        metric_cols[1].metric("Pass rate", f"{run['pass_rate']:.0%}")
        metric_cols[2].metric("Cases", f"{run['passed_cases']}/{run['total_cases']}")

        st.markdown("#### Per-check pass rates")
        for check_name, rate in run["summary"].items():
            st.write(f"**{check_name}**: {rate:.0%}")

        with st.expander("Per-case results"):
            for case in run["results"]:
                status = "PASS" if case["passed"] else "FAIL"
                st.write(f"[{status}] {case['case_id']}")
                for note in case.get("notes", []):
                    st.caption(f"  - {note}")
