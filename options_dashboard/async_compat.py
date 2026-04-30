"""Async compatibility helpers (Python 3.14-safe)."""
from __future__ import annotations

import asyncio


def ensure_event_loop() -> None:
    """Ensure the current thread has an event loop (Streamlit ScriptRunner-safe)."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        try:
            asyncio.get_event_loop()
        except RuntimeError:
            asyncio.set_event_loop(asyncio.new_event_loop())
