# SPDX-License-Identifier: MIT
"""Streaming and progress notification helpers for long-running MCP tools.

Provides:
- ProgressReporter: Context manager for sending progress notifications
- StreamingToolWrapper: Wraps tool handlers to support chunked/streaming responses
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, AsyncIterator

from mcp.types import TextContent

if TYPE_CHECKING:
    from mcp.server.session import ServerSession
    from mcp.types import ProgressToken

logger = logging.getLogger(__name__)


class ProgressReporter:
    """Send progress notifications during long-running tool execution.

    Usage:
        reporter = ProgressReporter(session, progress_token, total=100)
        await reporter.report(25, "Processing batch 1/4...")
        await reporter.report(50, "Processing batch 2/4...")
        await reporter.complete("Done")
    """

    def __init__(
        self,
        session: ServerSession,
        progress_token: ProgressToken,
        total: float | None = None,
    ) -> None:
        self._session = session
        self._token = progress_token
        self._total = total
        self._current: float = 0.0

    async def report(
        self,
        progress: float,
        message: str | None = None,
    ) -> None:
        """Send a progress notification."""
        self._current = progress
        await self._session.send_progress_notification(
            progress_token=self._token,
            progress=progress,
            total=self._total,
            message=message,
        )

    async def advance(
        self,
        delta: float,
        message: str | None = None,
    ) -> None:
        """Advance progress by a delta amount."""
        self._current += delta
        await self.report(self._current, message)

    async def complete(self, message: str | None = None) -> None:
        """Mark progress as complete."""
        final = self._total if self._total is not None else self._current
        await self.report(final, message or "Complete")


@asynccontextmanager
async def progress_context(
    session: ServerSession,
    progress_token: ProgressToken | None,
    total: float | None = None,
) -> AsyncIterator[ProgressReporter | None]:
    """Context manager that yields a ProgressReporter if a token is provided.

    Usage:
        async with progress_context(session, token, total=100) as reporter:
            if reporter:
                await reporter.report(50, "Halfway done")
    """
    if progress_token is None:
        yield None
        return

    reporter = ProgressReporter(session, progress_token, total)
    try:
        yield reporter
    finally:
        logger.debug("Ignoring streaming error: %s", reporter)


def text_result(text: str) -> list[TextContent]:
    """Create a standard text content result for tool responses."""
    return [TextContent(type="text", text=text)]


def error_result(message: str) -> list[TextContent]:
    """Create an error text content result for tool responses."""
    return [TextContent(type="text", text=f"Error: {message}")]
