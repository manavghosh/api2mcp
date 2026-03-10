# SPDX-License-Identifier: MIT
"""Plan generation node for PlannerGraph."""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


async def generate_plan(state: dict[str, Any], config: dict[str, Any] | None = None) -> dict[str, Any]:
    """Extract the LLM response and parse it into plan_raw in state."""
    _ = config
    messages = state.get("messages", [])
    plan_raw = str(messages[-1].content) if messages else ""
    logger.debug("generate_plan: extracted plan_raw length=%d", len(plan_raw))
    return {**state, "plan_raw": plan_raw}
