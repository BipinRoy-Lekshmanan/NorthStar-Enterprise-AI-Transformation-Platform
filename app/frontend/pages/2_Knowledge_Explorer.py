"""Knowledge Explorer page (Milestone 7) -- browse/filter the indexed
knowledge catalog, run semantic search (no answer generation), and
(administrator only) trigger ingestion/indexing/a confirmed full
rebuild. Entirely through the platform API.
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

st.set_page_config(page_title="Knowledge Explorer", page_icon="\U0001F4DA", layout="wide")
init_session()

st.title("Knowledge Explorer")
st.caption("Browse and search Northstar's internal knowledge base. Search returns scored excerpts, not generated answers.")

user = get_current_user()
if user is None:
    st.warning("Enter an API key on the Home page to explore the knowledge base.")
    st.stop()

client = get_api_client()

try:
    stats = client.knowledge_stats()
except ApiClientError as exc:
    st.error(f"Could not load knowledge base statistics: {exc.message}")
    st.stop()

stat_cols = st.columns(3)
stat_cols[0].metric("Documents", stats["document_count"])
stat_cols[1].metric("Chunks", stats["chunk_count"])
stat_cols[2].metric("Domains", len(stats["domains"]))

tab_browse, tab_search, tab_admin = st.tabs(["Browse catalog", "Semantic search", "Administration"])

with tab_browse:
    st.markdown("### Filter documents")
    filter_cols = st.columns(4)
    title_filter = filter_cols[0].text_input("Title contains", key="kb_title")
    status_filter = filter_cols[1].selectbox("Status", ["", "Approved", "Draft", "Deprecated"], key="kb_status")
    owner_filter = filter_cols[2].text_input("Owner contains", key="kb_owner")
    domain_filter = filter_cols[3].selectbox("Domain", [""] + stats["domains"], key="kb_domain")

    page = st.number_input("Page", min_value=1, value=1, step=1, key="kb_page")

    try:
        result = client.list_documents(
            page=page, page_size=10, title=title_filter, status=status_filter,
            owner=owner_filter, domain=domain_filter,
        )
    except ApiClientError as exc:
        st.error(f"Could not load documents: {exc.message}")
    else:
        st.caption(f"{result['total_items']} matching documents -- page {result['page']} of {max(result['total_pages'], 1)}")
        for doc in result["items"]:
            with st.container(border=True):
                st.markdown(f"#### {doc['title'] or doc['source_file']}")
                meta_cols = st.columns(4)
                meta_cols[0].caption(f"Document ID: `{doc['document_id'] or 'n/a'}`")
                meta_cols[1].caption(f"Domain: {doc['domain']}")
                meta_cols[2].caption(f"Status: {doc['status'] or 'n/a'}")
                meta_cols[3].caption(f"Owner: {doc['owner'] or 'n/a'}")
                st.write(f"**Chunks:** {doc['chunk_count']}")
                if doc["section_titles"]:
                    st.write("**Sections:** " + ", ".join(doc["section_titles"][:8]))

with tab_search:
    st.markdown("### Semantic search")
    question = st.text_input("Search phrase", key="kb_search_question")
    search_cols = st.columns(2)
    top_k = search_cols[0].slider("Results", min_value=1, max_value=20, value=5, key="kb_search_top_k")
    include_full_text = search_cols[1].checkbox("Show full chunk text", key="kb_search_full_text")

    if st.button("Search", type="primary", disabled=not question.strip()):
        try:
            with st.spinner("Searching..."):
                response = client.search_knowledge(question=question, top_k=top_k, include_full_text=include_full_text)
        except ApiClientError as exc:
            st.error(f"{exc.code or 'ERROR'}: {exc.message}")
        else:
            st.caption(f"Searched {response['total_indexed_chunks']} indexed chunks.")
            for result in response["results"]:
                with st.container(border=True):
                    st.markdown(f"**{result['document_title'] or result['source_file']}** -- score {result['score']:.3f}")
                    if result["section_title"]:
                        st.caption(result["section_title"])
                    st.write(result["excerpt"])

with tab_admin:
    if user["role"] != "administrator":
        st.info("Ingestion, indexing, and rebuild actions require the administrator role.")
    else:
        st.markdown("### Knowledge base administration")
        st.caption("These actions re-read the knowledge base from disk and update the vector index. All actions are audit-logged.")

        admin_cols = st.columns(2)
        with admin_cols[0]:
            if st.button("Run ingestion"):
                try:
                    with st.spinner("Running ingestion..."):
                        summary = client.run_ingestion()
                except ApiClientError as exc:
                    st.error(f"{exc.code or 'ERROR'}: {exc.message}")
                else:
                    st.success(
                        f"Loaded {summary['documents_loaded']} documents "
                        f"({summary['documents_failed']} failed), {summary['chunks_created']} chunks."
                    )
        with admin_cols[1]:
            if st.button("Run incremental indexing"):
                try:
                    with st.spinner("Indexing..."):
                        report = client.run_index()
                except ApiClientError as exc:
                    st.error(f"{exc.code or 'ERROR'}: {exc.message}")
                else:
                    st.success(
                        f"Added {report['added']}, removed {report['removed']}, "
                        f"unchanged {report['unchanged']} (total {report['total']})."
                    )

        st.markdown("#### Full rebuild")
        st.warning("This deletes and re-indexes the entire vector store. Type REBUILD (exact case) to confirm.")
        confirmation = st.text_input("Confirmation phrase", key="kb_rebuild_confirmation")
        if st.button("Run full rebuild", type="primary", disabled=confirmation != "REBUILD"):
            try:
                with st.spinner("Rebuilding..."):
                    report = client.run_rebuild(confirmation)
            except ApiClientError as exc:
                st.error(f"{exc.code or 'ERROR'}: {exc.message}")
            else:
                st.success(f"Rebuild complete: {report['added']} added, {report['total']} total chunks indexed.")
