from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Dict

import streamlit as st


VALID_ROLES = {"loader", "admin"}


@dataclass
class AuthConfig:
    enabled: bool
    users: Dict[str, tuple[str, str]]


def _to_bool(value: str, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def load_auth_config() -> AuthConfig:
    enabled = _to_bool(os.getenv("DL_AUTH_REQUIRED"), default=False)
    users: Dict[str, tuple[str, str]] = {}

    raw = (os.getenv("DL_USERS") or "").strip()
    if raw:
        for item in raw.split(","):
            parts = [p.strip() for p in item.split(":")]
            if len(parts) != 3:
                continue
            username, password, role = parts
            role = role.lower()
            if not username or role not in VALID_ROLES:
                continue
            users[username] = (password, role)

    return AuthConfig(enabled=enabled, users=users)


def ensure_auth(config: AuthConfig) -> tuple[str, str]:
    if "auth_user" not in st.session_state:
        st.session_state["auth_user"] = "anonymous"
    if "auth_role" not in st.session_state:
        st.session_state["auth_role"] = "loader"

    if not config.enabled:
        return st.session_state["auth_user"], st.session_state["auth_role"]

    st.sidebar.subheader("Authentication")
    if st.session_state.get("auth_user") != "anonymous":
        st.sidebar.success(
            f"Signed in as `{st.session_state['auth_user']}` ({st.session_state['auth_role']})"
        )
        if st.sidebar.button("Logout"):
            st.session_state["auth_user"] = "anonymous"
            st.session_state["auth_role"] = "loader"
            st.rerun()
        return st.session_state["auth_user"], st.session_state["auth_role"]

    if not config.users:
        st.error("Auth is enabled, but DL_USERS is not configured.")
        st.stop()

    user = st.sidebar.text_input("Username", key="login_user")
    password = st.sidebar.text_input("Password", type="password", key="login_password")
    if st.sidebar.button("Login"):
        item = config.users.get(user)
        if not item or item[0] != password:
            st.sidebar.error("Invalid credentials.")
            st.stop()
        st.session_state["auth_user"] = user
        st.session_state["auth_role"] = item[1]
        st.rerun()

    st.info("Please sign in to use this app.")
    st.stop()


def require_role(role: str, allowed: set[str]) -> None:
    if role not in allowed:
        raise PermissionError("You do not have enough permissions for this action.")
