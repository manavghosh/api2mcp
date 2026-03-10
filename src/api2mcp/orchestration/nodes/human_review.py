# SPDX-License-Identifier: MIT
"""Human review interrupt node for conversational/approval workflows."""
from __future__ import annotations
import logging
from typing import Any

logger = logging.getLogger(__name__)


async def request_human_review(state: dict[str, Any], config: dict[str, Any] | None = None) -> dict[str, Any]:
    """Interrupt execution and surface a review request to the human."""
    _ = config  # reserved for future LangGraph config injection
    logger.info("human_review: awaiting approval for %r", state.get("pending_action"))
    return {**state, "awaiting_review": True}
