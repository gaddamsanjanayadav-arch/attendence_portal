# Attendence/config.py

import os
import streamlit as st
from dotenv import load_dotenv

# Load .env for local development only
load_dotenv()


def get_env(var_name: str, default=None):
    """
    Get environment variable safely.
    Priority:
    1️⃣ Streamlit secrets (for deployment)
    2️⃣ OS environment / .env (for local run)
    """

    # Try Streamlit secrets first
    try:
        if var_name in st.secrets:
            return st.secrets[var_name]
    except Exception:
        # Happens when not running inside Streamlit
        pass

    # Fallback to system environment / .env
    value = os.getenv(var_name)

    if value is not None:
        return value

    return default