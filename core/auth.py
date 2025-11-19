from __future__ import annotations

import os
from typing import Tuple

import streamlit as st


def init_auth_state() -> None:
    if "authenticated" not in st.session_state:
        st.session_state["authenticated"] = False


def get_credentials() -> Tuple[str | None, str | None]:
    username = st.secrets.get("login", {}).get("username") or os.getenv("VALID_USERNAME")
    password = st.secrets.get("login", {}).get("password") or os.getenv("VALID_PASSWORD")
    return username, password


def authenticate(username: str, password: str) -> bool:
    valid_username, valid_password = get_credentials()
    return username == valid_username and password == valid_password


def require_auth(message: str = "Faça login na página inicial para acessar este conteúdo.") -> None:
    init_auth_state()
    if not st.session_state["authenticated"]:
        st.warning(message)
        st.stop()

