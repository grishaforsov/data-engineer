from __future__ import annotations

import time
import streamlit as st


def ui_log(message: str) -> None:
    ts = time.strftime("%H:%M:%S")
    st.session_state.setdefault("logs", [])
    st.session_state["logs"].append(f"[{ts}] {message}")


def render_logs() -> None:
    st.session_state.setdefault("logs", [])
    st.text_area("Логи", value="\n".join(st.session_state["logs"]), height=260)
