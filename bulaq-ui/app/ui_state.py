import streamlit as st
from ui_ai import AI_MODEL_DEFAULT

DEFAULTS = {
    "runtime_hist": [],
    "last_runtime_pull": 0.0,
    "uuid_query": "",
    "selected_uuid": "",
    "selected_vtype": "all",
    "selected_status": "all",
    "autorefresh": True,
    "refresh_sec": 5,
    "ai_model": AI_MODEL_DEFAULT,
    "ai_last_result": None,
    "ai_last_uuid": "",
    "explorer_limit": 100,
    "row_selector": "",
}


def init_session_state():
    for k, v in DEFAULTS.items():
        if k not in st.session_state:
            st.session_state[k] = v