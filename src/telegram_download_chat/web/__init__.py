"""Web interface for telegram-download-chat using Streamlit."""

import os
import sys

import streamlit.web.cli as stcli


def main() -> int:
    """Run the Streamlit application."""
    script_path = os.path.join(os.path.dirname(__file__), "streamlit_app.py")
    sys.argv = ["streamlit", "run", script_path]
    return stcli.main()


__all__ = ["main"]
