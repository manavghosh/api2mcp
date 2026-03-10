# SPDX-License-Identifier: MIT
"""Rate limiting middleware for MCP tool calls.

:class:`RateLimitMiddleware` wraps a tool call handler and enforces local
token-bucket rate limits per tool.  It also parses upstream rate-limit headers
from tool response payloads and adapts the bucket accordingly (so that the
server voluntarily backs off before the upstream API returns HTTP 429).

Architecture
------------
Each tool gets its own :class:`~.bucket.TokenBucket` (lazily created from the
:class:`~.config.RateLimitConfig`).  On every tool call:

1. Try to consume a token from the tool's bucket.
2. If the bucket is empty, retry up to *max_retries* times with exponential
   backoff (via :mod:`tenacity`).
3. Forward the call to the downstream handler.
4. Parse any rate-limit headers embedded in the response and drain the bucket
   proportionally so future calls self-throttle.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Callable, Awaitable

from mcp.types import TextContent

from api2mcp.ratelimit.bucket import TokenBucket
from api2mcp.ratelimit.config import BucketConfig, RateLimitConfig
from api2mcp.ratelimit.exceptions import RateLimitError
from api2mcp.ratelimit.headers import parse_rate_limit_headers
from api2mcp.ratelimit.retry import build_retry

logger = logging.getLogger(__name__)

ToolHandler = Callable[[str, dict[str, Any] | None], Awaitable[list[TextContent]]]


class RateLimitMiddleware:
    """Middleware that applies token-bucket rate limiting to every tool call.

    Args:
        config: Rate limit configuration.

    Usage::

        middleware = RateLimitMiddleware(config)
        wrapped = middleware.wrap(raw_handler)
        # Use `wrapped` as the MCP call_tool handler
    """

    def __init__(self, config: RateLimitConfig | None = None) -> None:
        self._config = config or RateLimitConfig()
        # Lazily created buckets keyed by tool name
        self._buckets: dict[str, TokenBucket] = {}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def wrap(self, handler: ToolHandler) -> ToolHandler:
        """Return a new handler with rate limiting applied."""
        config = self._config

        async def rate_limited_handler(
            name: str, arguments: dict[str, Any] | None
        ) -> list[TextContent]:
            if not config.enabled:
                return await handler(name, arguments)

            bucket = self._get_or_create_bucket(name)

            # Retry loop — tenacity handles backoff between attempts
            retrying = build_retry(max_retries=config.max_retries)
            async for attempt in retrying:
                with attempt:
                    consumed = await bucket.consume()
                    if not consumed:
                        wait = await bucket.wait_time()
                        raise RateLimitError(
                            f"Rate limit exceeded for tool '{name}'",
                            retry_after=wait,
                            tool_name=name,
                        )

            # Token consumed — forward to downstream handler
            try:
                result = await handler(name, arguments)
            except RateLimitError:
                raise
            except Exception:
                raise

            # Adapt bucket based on upstream response headers (best-effort)
            self._adapt_from_response(name, result, bucket)

            return result

        if not config.raise_on_limit:
            return _wrap_error_as_response(rate_limited_handler)
        return rate_limited_handler

    def get_bucket(self, tool_name: str) -> TokenBucket | None:
        """Return the bucket for *tool_name* if it has been created, else ``None``."""
        return self._buckets.get(tool_name)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_or_create_bucket(self, tool_name: str) -> TokenBucket:
        if tool_name not in self._buckets:
            cfg: BucketConfig = self._config.bucket_for(tool_name)
            self._buckets[tool_name] = TokenBucket(
                capacity=cfg.capacity,
                refill_rate=cfg.refill_rate,
            )
        return self._buckets[tool_name]

    @staticmethod
    def _adapt_from_response(
        tool_name: str, result: list[TextContent], bucket: TokenBucket
    ) -> None:
        """Drain bucket tokens based on upstream X-RateLimit-Remaining header.

        MCP tools often embed response metadata (including HTTP headers) inside
        the JSON payload of a TextContent.  We look for a ``_headers`` key that
        contains the upstream response headers and parse them.
        """
        if not result:
            return

        first = result[0]
        if first.type != "text":
            return

        try:
            data = json.loads(first.text)
        except (json.JSONDecodeError, TypeError):
            return

        raw_headers: dict[str, str] | None = data.get("_headers") if isinstance(data, dict) else None
        if not raw_headers or not isinstance(raw_headers, dict):
            return

        rl = parse_rate_limit_headers(raw_headers)
        if rl.is_exhausted:
            logger.warning(
                "Upstream rate limit exhausted for tool '%s'; draining local bucket.",
                tool_name,
            )
            bucket.drain(bucket.capacity)
        elif rl.remaining is not None and rl.limit is not None and rl.limit > 0:
            # Proportionally drain: if 10% remaining → drain 90% of capacity
            fraction_used = 1.0 - (rl.remaining / rl.limit)
            tokens_to_drain = fraction_used * bucket.capacity
            if tokens_to_drain > 0:
                bucket.drain(tokens_to_drain)


def _wrap_error_as_response(handler: ToolHandler) -> ToolHandler:
    """Catch :class:`RateLimitError` and return it as an MCP TextContent error."""

    async def safe_handler(
        name: str, arguments: dict[str, Any] | None
    ) -> list[TextContent]:
        try:
            return await handler(name, arguments)
        except RateLimitError as exc:
            logger.warning("Rate limit for tool '%s': %s", name, exc)
            payload: dict[str, Any] = {
                "error": str(exc),
                "code": exc.code,
            }
            if exc.retry_after is not None:
                payload["retry_after"] = exc.retry_after
            return [TextContent(type="text", text=json.dumps(payload))]

    return safe_handler
