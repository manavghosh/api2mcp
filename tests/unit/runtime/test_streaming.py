"""Unit tests for streaming helpers (TASK-027)."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from api2mcp.runtime.streaming import (
    ProgressReporter,
    error_result,
    progress_context,
    text_result,
)


class TestTextResult:
    def test_returns_text_content(self) -> None:
        result = text_result("hello")
        assert len(result) == 1
        assert result[0].type == "text"
        assert result[0].text == "hello"


class TestErrorResult:
    def test_returns_error_content(self) -> None:
        result = error_result("something broke")
        assert len(result) == 1
        assert result[0].text == "Error: something broke"


class TestProgressReporter:
    @pytest.mark.asyncio
    async def test_report_sends_notification(self) -> None:
        session = MagicMock()
        session.send_progress_notification = AsyncMock()

        reporter = ProgressReporter(session, "token-1", total=100.0)
        await reporter.report(50.0, "Halfway")

        session.send_progress_notification.assert_called_once_with(
            progress_token="token-1",
            progress=50.0,
            total=100.0,
            message="Halfway",
        )

    @pytest.mark.asyncio
    async def test_advance_increments(self) -> None:
        session = MagicMock()
        session.send_progress_notification = AsyncMock()

        reporter = ProgressReporter(session, "token-2", total=10.0)
        await reporter.advance(3.0, "Step 1")
        await reporter.advance(4.0, "Step 2")

        calls = session.send_progress_notification.call_args_list
        assert calls[0].kwargs["progress"] == 3.0
        assert calls[1].kwargs["progress"] == 7.0

    @pytest.mark.asyncio
    async def test_complete_sets_total(self) -> None:
        session = MagicMock()
        session.send_progress_notification = AsyncMock()

        reporter = ProgressReporter(session, "token-3", total=100.0)
        await reporter.complete()

        session.send_progress_notification.assert_called_once_with(
            progress_token="token-3",
            progress=100.0,
            total=100.0,
            message="Complete",
        )


class TestProgressContext:
    @pytest.mark.asyncio
    async def test_yields_none_without_token(self) -> None:
        session = MagicMock()
        async with progress_context(session, None) as reporter:
            assert reporter is None

    @pytest.mark.asyncio
    async def test_yields_reporter_with_token(self) -> None:
        session = MagicMock()
        session.send_progress_notification = AsyncMock()

        async with progress_context(session, "tok-1", total=50.0) as reporter:
            assert reporter is not None
            assert isinstance(reporter, ProgressReporter)
