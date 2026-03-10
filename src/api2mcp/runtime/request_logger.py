# SPDX-License-Identifier: MIT
"""Request/response logging middleware with sensitive field redaction."""
from __future__ import annotations

import logging
import re
import time
from typing import Any

logger = logging.getLogger(__name__)

#: Regex matching field names that should be redacted.
_SENSITIVE_RE = re.compile(
    r"token|secret|password|passwd|key|auth|card|credential|private",
    re.IGNORECASE,
)

_REDACTED = "[REDACTED]"


def redact_params(params: dict[str, Any]) -> dict[str, Any]:
    """Return a copy of *params* with sensitive values replaced by [REDACTED].

    Sensitive fields are identified by key name matching common patterns:
    token, secret, password, key, auth, card, credential, private.
    Nested dicts are recursively redacted.
    """
    result: dict[str, Any] = {}
    for k, v in params.items():
        if isinstance(v, dict):
            result[k] = redact_params(v)
        elif _SENSITIVE_RE.search(str(k)):
            result[k] = _REDACTED
        else:
            result[k] = v
    return result


def log_tool_call(
    tool_name: str,
    params: dict[str, Any],
    *,
    server_name: str = "",
    log_level: int = logging.DEBUG,
) -> float:
    """Log an incoming MCP tool call and return the start timestamp.

    Args:
        tool_name:   Name of the tool being called.
        params:      Tool input parameters (will be redacted before logging).
        server_name: MCP server name (for multi-server deployments).
        log_level:   Python logging level for this message.

    Returns:
        Start timestamp (from time.perf_counter()) for latency calculation.
    """
    safe_params = redact_params(params)
    logger.log(
        log_level,
        "TOOL_CALL server=%r tool=%r params=%r",
        server_name,
        tool_name,
        safe_params,
    )
    return time.perf_counter()


def log_tool_response(
    tool_name: str,
    start_time: float,
    *,
    status: str = "ok",
    response_size: int = 0,
    include_body: bool = False,
    response_body: Any = None,
    log_level: int = logging.DEBUG,
) -> None:
    """Log the response for a completed tool call.

    Args:
        tool_name:     Name of the tool that was called.
        start_time:    Timestamp returned by log_tool_call().
        status:        'ok' or 'error'.
        response_size: Size of the response payload in bytes.
        include_body:  If True, log the response body (use with caution).
        response_body: The response payload (only logged if include_body=True).
        log_level:     Python logging level for this message.
    """
    latency_ms = (time.perf_counter() - start_time) * 1000
    if include_body and response_body is not None:
        logger.log(
            log_level,
            "TOOL_RESPONSE tool=%r status=%r latency_ms=%.1f size=%d body=%r",
            tool_name,
            status,
            latency_ms,
            response_size,
            response_body,
        )
    else:
        logger.log(
            log_level,
            "TOOL_RESPONSE tool=%r status=%r latency_ms=%.1f size=%d",
            tool_name,
            status,
            latency_ms,
            response_size,
        )
