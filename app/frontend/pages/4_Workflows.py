"""Workflows page (Milestone 7) -- browse the 5 enterprise review
workflows, execute one via a generated form / a JSON example / an
uploaded file, and inspect past executions (stages, findings, evidence
gaps, conflicts, citations, final report). Approval decisions
themselves live on the separate Approvals page -- this page can
execute, resume (once approved), and cancel, but never approves.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

import streamlit as st

from app.frontend.api_client import ApiClientError
from app.frontend.components.forms import render_workflow_form
from app.frontend.session import get_active_execution, get_api_client, get_current_user, init_session, set_active_execution

st.set_page_config(page_title="Workflows", page_icon="\U0001F4CB", layout="wide")
init_session()

st.title("Workflows")
st.caption(
    "Controlled, human-checkpointed enterprise review workflows -- each stage is a deterministic, "
    "auditable step over the shared grounded pipeline, never an autonomous agent making its own plan."
)

user = get_current_user()
if user is None:
    st.warning("Enter an API key on the Home page to use workflows.")
    st.stop()

client = get_api_client()

try:
    workflows = client.list_workflows()
except ApiClientError as exc:
    st.error(f"Could not load workflows: {exc.message}")
    st.stop()

can_execute = user["role"] in ("engineer", "reviewer", "administrator")

tab_run, tab_executions = st.tabs(["Run a workflow", "Executions"])

with tab_run:
    workflow_ids = [w["workflow_id"] for w in workflows]
    labels = {w["workflow_id"]: f"{w['name']} (v{w['version']})" for w in workflows}
    selected_id = st.selectbox("Workflow", workflow_ids, format_func=lambda wid: labels[wid])

    try:
        detail = client.get_workflow(selected_id)
    except ApiClientError as exc:
        st.error(f"Could not load workflow detail: {exc.message}")
        st.stop()

    st.write(detail["description"])
    with st.expander(f"Stages ({len(detail['stages'])})"):
        for stage in detail["stages"]:
            approval = " -- pauses for human approval" if stage["human_approval_required"] else ""
            st.write(f"**{stage['name']}** [{stage['stage_type']}]{approval}")

    if not can_execute:
        st.info("Executing workflows requires the engineer role or higher.")
    else:
        input_mode = st.radio("Input source", ["Fill form", "Load example", "Upload JSON"], horizontal=True)
        execution_result = None

        if input_mode == "Fill form":
            inputs = render_workflow_form(selected_id, detail["input_schema"])
            if inputs is not None:
                try:
                    with st.spinner("Executing workflow..."):
                        execution_result = client.execute_workflow(selected_id, inputs)
                except ApiClientError as exc:
                    st.error(f"{exc.code or 'ERROR'}: {exc.message}")

        elif input_mode == "Load example":
            try:
                examples = client.list_workflow_examples(selected_id)
            except ApiClientError as exc:
                st.error(f"Could not load examples: {exc.message}")
                examples = []
            if not examples:
                st.info("No example inputs are available for this workflow.")
            else:
                example_names = [e["name"] for e in examples]
                chosen = st.selectbox("Example", example_names)
                example_inputs = next(e["inputs"] for e in examples if e["name"] == chosen)
                st.json(example_inputs)
                if st.button("Run with this example", type="primary"):
                    try:
                        with st.spinner("Executing workflow..."):
                            execution_result = client.execute_workflow(selected_id, example_inputs)
                    except ApiClientError as exc:
                        st.error(f"{exc.code or 'ERROR'}: {exc.message}")

        else:  # Upload JSON
            uploaded = st.file_uploader("Upload a JSON input file", type=["json"])
            if uploaded is not None:
                try:
                    uploaded_inputs = json.loads(uploaded.read().decode("utf-8"))
                except (json.JSONDecodeError, UnicodeDecodeError) as exc:
                    st.error(f"Uploaded file is not valid JSON: {exc}")
                    uploaded_inputs = None
                if uploaded_inputs is not None:
                    st.json(uploaded_inputs)
                    if st.button("Run with uploaded input", type="primary"):
                        try:
                            with st.spinner("Executing workflow..."):
                                execution_result = client.execute_workflow(selected_id, uploaded_inputs)
                        except ApiClientError as exc:
                            st.error(f"{exc.code or 'ERROR'}: {exc.message}")

        if execution_result is not None:
            set_active_execution(execution_result["execution_id"])
            st.success(f"Execution {execution_result['execution_id']} -- status: {execution_result['status']}")
            if execution_result["status"] == "awaiting_approval":
                st.info("This execution is paused for human approval. Use the Approvals page to decide it.")

with tab_executions:
    filter_workflow_id = st.selectbox("Filter by workflow", ["(all)"] + workflow_ids, key="exec_filter_workflow")
    try:
        result = client.list_executions(
            workflow_id=None if filter_workflow_id == "(all)" else filter_workflow_id, page_size=25,
        )
    except ApiClientError as exc:
        st.error(f"Could not load executions: {exc.message}")
        result = {"items": []}

    active_execution_id = get_active_execution()
    execution_ids = [e["execution_id"] for e in result["items"]]
    if not execution_ids:
        st.info("No executions yet -- run a workflow from the first tab.")
    else:
        default_index = execution_ids.index(active_execution_id) if active_execution_id in execution_ids else 0
        selected_execution_id = st.selectbox(
            "Execution",
            execution_ids,
            index=default_index,
            format_func=lambda eid: next(
                f"{e['workflow_id']} -- {e['status']} -- {eid}" for e in result["items"] if e["execution_id"] == eid
            ),
        )

        try:
            execution = client.get_execution(selected_execution_id)
        except ApiClientError as exc:
            st.error(f"Could not load execution: {exc.message}")
            execution = None

        if execution is not None:
            status_cols = st.columns(3)
            status_cols[0].metric("Status", execution["status"])
            status_cols[1].metric("Findings", len(execution["findings"]))
            status_cols[2].metric("Evidence gaps", len(execution["evidence_gaps"]))

            if execution["status"] == "awaiting_approval":
                st.info("Awaiting human approval -- use the Approvals page to approve, reject, or request changes.")

            action_cols = st.columns(2)
            if can_execute and execution["status"] == "running":
                if action_cols[0].button("Resume"):
                    try:
                        client.resume_execution(selected_execution_id)
                        st.rerun()
                    except ApiClientError as exc:
                        st.error(f"{exc.code or 'ERROR'}: {exc.message}")
            if can_execute and execution["status"] not in ("completed", "failed", "cancelled", "changes_requested"):
                if action_cols[1].button("Cancel", type="secondary"):
                    try:
                        client.cancel_execution(selected_execution_id)
                        st.rerun()
                    except ApiClientError as exc:
                        st.error(f"{exc.code or 'ERROR'}: {exc.message}")

            with st.expander("Stages", expanded=False):
                for stage in execution["stage_results"]:
                    advisor = f" ({stage['advisor_name']})" if stage["advisor_name"] else ""
                    st.write(f"[{stage['status']}] {stage['stage_name']}{advisor}")

            if execution["findings"]:
                with st.expander(f"Findings ({len(execution['findings'])})"):
                    for finding in execution["findings"]:
                        blocking = " [BLOCKING]" if finding["blocking"] else ""
                        st.write(f"**[{finding['severity'].upper()}{blocking}] {finding['title']}** -- {finding['description']}")

            if execution["conflicts"]:
                with st.expander(f"Conflicts ({len(execution['conflicts'])})"):
                    for conflict in execution["conflicts"]:
                        st.write(f"**{conflict['title']}** -- {', '.join(conflict['source_advisors'])}")
                        st.write(conflict["description"])

            if execution["evidence_gaps"]:
                with st.expander(f"Evidence gaps ({len(execution['evidence_gaps'])})"):
                    for gap in execution["evidence_gaps"]:
                        blocking = " [BLOCKING]" if gap["blocking"] else ""
                        st.write(f"[{gap['severity'].upper()}{blocking}] {gap['field']}: {gap['description']}")

            if execution["citations"]:
                with st.expander(f"Sources ({len(execution['citations'])})"):
                    for citation in execution["citations"]:
                        st.write(f"- {citation['document_title'] or citation['source_file']} ({citation['section_title'] or 'n/a'})")

            if execution["status"] == "completed":
                try:
                    report = client.get_workflow_report(selected_execution_id)
                except ApiClientError as exc:
                    st.error(f"Could not load report: {exc.message}")
                else:
                    st.markdown("#### Final report")
                    for header, content in report["sections"].items():
                        st.markdown(f"**{header}**")
                        st.write(content or "(no content)")
