# SPDX-License-Identifier: MIT
"""Routing: route to next plan step, aggregation, or completion."""
from __future__ import annotations
from typing import Any


def route_plan_step(state: dict[str, Any]) -> str:
    """Route after a plan step completes.

    Returns 'execute_step' if more steps remain, 'aggregate' if done.
    """
    steps = state.get("plan_steps", [])
    current = state.get("current_step_index", 0)
    if current + 1 < len(steps):
        return "execute_step"
    return "aggregate"
