"""Tests for `app.frontend.session` -- `st.session_state` helpers
(Milestone 7). Streamlit's `session_state` works in "bare mode" outside
a running `streamlit run` process (with a harmless warning), so these
run as plain pytest functions with no Streamlit server needed.
"""

import streamlit as st

from app.frontend import session


def _reset_state():
    st.session_state.clear()


def test_init_session_sets_defaults():
    _reset_state()
    session.init_session()
    assert st.session_state[session.API_KEY_STATE] == ""
    assert st.session_state[session.CURRENT_USER_STATE] is None
    assert st.session_state[session.BASE_URL_STATE] == session.DEFAULT_BASE_URL
    assert st.session_state[session.QUESTION_HISTORY_STATE] == []
    assert st.session_state[session.ACTIVE_EXECUTION_STATE] is None


def test_init_session_does_not_overwrite_existing_values():
    _reset_state()
    session.init_session()
    st.session_state[session.API_KEY_STATE] = "existing-key"
    session.init_session()
    assert st.session_state[session.API_KEY_STATE] == "existing-key"


def test_set_api_key_clears_cached_current_user():
    _reset_state()
    session.init_session()
    st.session_state[session.CURRENT_USER_STATE] = {"username": "a", "role": "viewer"}
    session.set_api_key("new-key")
    assert st.session_state[session.API_KEY_STATE] == "new-key"
    assert st.session_state[session.CURRENT_USER_STATE] is None


def test_get_current_user_returns_none_without_api_key():
    _reset_state()
    session.init_session()
    assert session.get_current_user() is None


def test_get_current_user_returns_cached_value_without_calling_api():
    _reset_state()
    session.init_session()
    st.session_state[session.API_KEY_STATE] = "k"
    st.session_state[session.CURRENT_USER_STATE] = {"username": "cached", "role": "viewer"}
    assert session.get_current_user() == {"username": "cached", "role": "viewer"}


def test_add_question_to_history_prepends_and_dedupes():
    _reset_state()
    session.init_session()
    session.add_question_to_history("first")
    session.add_question_to_history("second")
    session.add_question_to_history("first")  # re-asking moves it to the front, not duplicated
    assert session.get_question_history() == ["first", "second"]


def test_add_question_to_history_caps_at_max_items():
    _reset_state()
    session.init_session()
    for i in range(session.MAX_HISTORY_ITEMS + 5):
        session.add_question_to_history(f"q{i}")
    assert len(session.get_question_history()) == session.MAX_HISTORY_ITEMS


def test_active_execution_set_and_get():
    _reset_state()
    session.init_session()
    assert session.get_active_execution() is None
    session.set_active_execution("exec-123")
    assert session.get_active_execution() == "exec-123"


def test_clear_session_history_resets_history_and_active_execution():
    _reset_state()
    session.init_session()
    session.add_question_to_history("q1")
    session.set_active_execution("exec-1")
    session.clear_session_history()
    assert session.get_question_history() == []
    assert session.get_active_execution() is None
