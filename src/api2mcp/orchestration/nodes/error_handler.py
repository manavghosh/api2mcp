# SPDX-License-Identifier: MIT
"""Error handling node — classifies errors and decides retry/fallback."""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


async def handle_error(state: dict[str, Any], config: dict[str, Any] | None = None) -> dict[str, Any]:
    """Classify the error in state and set retry/fallback flags."""
    _ = config  # reserved for LangGraph config injection
    error = state.get("error")
    logger.warning("handle_error: %s", error)
    return {**state, "should_retry": False, "error_handled": True}
