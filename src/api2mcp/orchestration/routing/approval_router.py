# SPDX-License-Identifier: MIT
"""Routing: decide whether to request human review or execute directly."""
from __future__ import annotations

from typing import Any


def route_for_approval(state: dict[str, Any]) -> str:
    """Route to human review if the pending action requires approval."""
    if state.get("requires_approval"):
        return "human_review"
    return "execute"
