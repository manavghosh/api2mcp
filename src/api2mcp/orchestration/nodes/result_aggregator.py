# SPDX-License-Identifier: MIT
"""Result aggregator node — combines intermediate results into final_result."""
from __future__ import annotations
import logging
from typing import Any

logger = logging.getLogger(__name__)


async def aggregate_results(state: dict[str, Any], config: dict[str, Any] | None = None) -> dict[str, Any]:
    """Build final_result from intermediate_results."""
    _ = config
    intermediate: dict[str, Any] = state.get("intermediate_results", {})
    final = "; ".join(f"{k}={v}" for k, v in intermediate.items()) if intermediate else "No results."
    logger.info("aggregate_results: final_result length=%d", len(final))
    return {**state, "final_result": final, "workflow_status": "completed"}
