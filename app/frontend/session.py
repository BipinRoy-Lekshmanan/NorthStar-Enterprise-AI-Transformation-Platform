"""Streamlit session-state helpers (Milestone 7).

No server-side session, no long-term memory -- everything here is
`st.session_state`, scoped to one browser tab's Streamlit session and
lost on refresh. Question history is deliberately kept only here, never
written to disk (the milestone's "may remain in Streamlit session
state, need not be persisted" requirement) -- and it never overrides a
freshly retrieved answer; it's just a list of past questions to re-ask.
"""

from __future__ import annotations

import os

import streamlit as st

from app.frontend.api_client import ApiClient, ApiClientError

API_KEY_STATE = "api_key"
CURRENT_USER_STATE = "current_user"
BASE_URL_STATE = "api_base_url"
QUESTION_HISTORY_STATE = "question_history"
ACTIVE_EXECUTION_STATE = "active_execution_id"

# Milestone 8: overridable via API_BASE_URL so the container image can
# point the UI at the API service (e.g. "http://api:8000" in
# docker-compose) without every user having to type it into the "API
# base URL" field by hand -- the field itself still lets it be changed
# per-session regardless.
DEFAULT_BASE_URL = os.environ.get("API_BASE_URL", "http://127.0.0.1:8000")
MAX_HISTORY_ITEMS = 20


def init_session() -> None:
    st.session_state.setdefault(API_KEY_STATE, "")
    st.session_state.setdefault(CURRENT_USER_STATE, None)
    st.session_state.setdefault(BASE_URL_STATE, DEFAULT_BASE_URL)
    st.session_state.setdefault(QUESTION_HISTORY_STATE, [])
    st.session_state.setdefault(ACTIVE_EXECUTION_STATE, None)


def get_api_client() -> ApiClient:
    return ApiClient(base_url=st.session_state[BASE_URL_STATE], api_key=st.session_state[API_KEY_STATE] or None)


def set_api_key(api_key: str) -> None:
    st.session_state[API_KEY_STATE] = api_key
    st.session_state[CURRENT_USER_STATE] = None  # force re-resolution against the new key


def get_current_user() -> dict | None:
    """Resolves and caches the current user for this session. Returns
    `None` (never raises) if unauthenticated or unreachable -- callers
    check for `None` and prompt for an API key rather than crash."""
    if st.session_state[CURRENT_USER_STATE] is not None:
        return st.session_state[CURRENT_USER_STATE]
    if not st.session_state[API_KEY_STATE]:
        return None
    try:
        user = get_api_client().current_user()
    except ApiClientError:
        return None
    st.session_state[CURRENT_USER_STATE] = user
    return user


def add_question_to_history(question: str) -> None:
    history = [question] + [q for q in st.session_state[QUESTION_HISTORY_STATE] if q != question]
    st.session_state[QUESTION_HISTORY_STATE] = history[:MAX_HISTORY_ITEMS]


def get_question_history() -> list[str]:
    return st.session_state[QUESTION_HISTORY_STATE]


def set_active_execution(execution_id: str | None) -> None:
    st.session_state[ACTIVE_EXECUTION_STATE] = execution_id


def get_active_execution() -> str | None:
    return st.session_state[ACTIVE_EXECUTION_STATE]


def clear_session_history() -> None:
    st.session_state[QUESTION_HISTORY_STATE] = []
    st.session_state[ACTIVE_EXECUTION_STATE] = None
