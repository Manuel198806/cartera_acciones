"""Async compatibility helpers (Python 3.14-safe)."""
from __future__ import annotations

import asyncio


def ensure_event_loop() -> None:
    """Ensure a default event loop exists before importing libs that expect one."""
    try:
        asyncio.get_event_loop()
    except RuntimeError:
        asyncio.set_event_loop(asyncio.new_event_loop())
