# SPDX-License-Identifier: MIT
"""Concurrency middleware for MCP tool call handlers.

:class:`ConcurrencyMiddleware` wraps a tool handler and enforces the
concurrency limits from :class:`~.config.ConcurrencyConfig`.  When the
configured limit is reached and the wait times out, it either raises
:class:`~.exceptions.ConcurrencyError` or returns an MCP-friendly error
``TextContent`` depending on the :attr:`~.config.ConcurrencyConfig.raise_on_limit`
flag.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Awaitable, Callable
from typing import Any

from mcp.types import TextContent

from api2mcp.concurrency.config import ConcurrencyConfig
from api2mcp.concurrency.exceptions import ConcurrencyError
from api2mcp.concurrency.limiter import ConcurrencyLimiter

logger = logging.getLogger(__name__)

ToolHandler = Callable[[str, dict[str, Any] | None], Awaitable[list[TextContent]]]


class ConcurrencyMiddleware:
    """Middleware that enforces concurrency limits on tool calls.

    Args:
        config: Concurrency configuration.
        limiter: Optional pre-built limiter.

    Usage::

        mw = ConcurrencyMiddleware(ConcurrencyConfig(max_concurrent=20))
        wrapped = mw.wrap(raw_handler)
        # Use ``wrapped`` as the MCP call_tool handler
    """

    def __init__(
        self,
        config: ConcurrencyConfig | None = None,
        limiter: ConcurrencyLimiter | None = None,
    ) -> None:
        self._config = config or ConcurrencyConfig()
        self._limiter = limiter or ConcurrencyLimiter(self._config)

    @property
    def limiter(self) -> ConcurrencyLimiter:
        """The underlying :class:`~.limiter.ConcurrencyLimiter`."""
        return self._limiter

    def wrap(self, handler: ToolHandler) -> ToolHandler:
        """Return a new handler with concurrency limiting applied."""
        config = self._config
        limiter = self._limiter

        async def limited_handler(
            name: str, arguments: dict[str, Any] | None
        ) -> list[TextContent]:
            if not config.enabled:
                return await handler(name, arguments)

            try:
                async with limiter.acquire(name):
                    return await handler(name, arguments)
            except asyncio.CancelledError:
                # Propagate cancellation immediately — do not wrap it
                raise
            except ConcurrencyError as exc:
                if config.raise_on_limit:
                    raise
                logger.warning(
                    "Concurrency limit for tool '%s': %s", name, exc
                )
                return [TextContent(
                    type="text",
                    text=json.dumps({
                        "error": str(exc),
                        "code": exc.code,
                        "limit": exc.limit,
                    }),
                )]

        return limited_handler
