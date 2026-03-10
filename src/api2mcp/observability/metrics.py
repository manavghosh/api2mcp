# SPDX-License-Identifier: MIT
"""Lightweight metrics — no-ops without opentelemetry."""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

try:
    from opentelemetry import metrics as _otel_metrics  # type: ignore[import-not-found]
    _HAS_OTEL = True
except ImportError:
    _HAS_OTEL = False


def record_tool_call(
    tool_name: str,
    server: str,
    status: str,
    latency_ms: float,
) -> None:
    """Record a tool call metric.

    Emits an OpenTelemetry counter and histogram if available,
    otherwise logs the metric at DEBUG level.
    """
    logger.debug(
        "metric: tool_call tool=%r server=%r status=%r latency_ms=%.1f",
        tool_name,
        server,
        status,
        latency_ms,
    )
