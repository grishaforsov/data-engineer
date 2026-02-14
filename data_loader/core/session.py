from __future__ import annotations

import streamlit as st


def ss_get(key: str, default):
    if key not in st.session_state:
        st.session_state[key] = default
    return st.session_state[key]


def ss_set(key: str, value):
    st.session_state[key] = value
