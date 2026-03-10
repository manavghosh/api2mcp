# SPDX-License-Identifier: MIT
"""Routing: decide retry, fallback, or failure after an error."""
from __future__ import annotations

from typing import Any


def route_on_error(state: dict[str, Any]) -> str:
    """Route based on whether the error handler decided to retry."""
    if state.get("should_retry"):
        return "retry"
    return "failure"
