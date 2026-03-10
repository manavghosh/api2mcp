# SPDX-License-Identifier: MIT
"""Plan execution node — executes one step from execution_plan."""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


async def execute_step(state: dict[str, Any], config: dict[str, Any] | None = None) -> dict[str, Any]:
    """Advance current_step_index by one and record status."""
    _ = config
    idx = state.get("current_step_index", 0)
    logger.debug("execute_step: advancing from step %d", idx)
    return {**state, "current_step_index": idx + 1}
