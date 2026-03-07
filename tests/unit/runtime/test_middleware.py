"""Unit tests for middleware stack (TASK-021, TASK-024)."""

import json

import pytest

from mcp.types import TextContent

from api2mcp.runtime.middleware import CallMetrics, MiddlewareStack, _summarize_args


class TestCallMetrics:
    def test_defaults(self) -> None:
        metrics = CallMetrics()
        assert metrics.total_calls == 0
        assert metrics.error_count == 0
        assert metrics.total_duration_ms == 0.0

    def test_avg_duration_zero_calls(self) -> None:
        metrics = CallMetrics()
        assert metrics.avg_duration_ms == 0.0

    def test_avg_duration(self) -> None:
        metrics = CallMetrics(total_calls=4, total_duration_ms=100.0)
        assert metrics.avg_duration_ms == 25.0


class TestMiddlewareStack:
    @pytest.mark.asyncio
    async def test_wraps_successful_call(self) -> None:
        stack = MiddlewareStack(enable_logging=False)

        async def handler(name: str, arguments: dict | None) -> list[TextContent]:
            return [TextContent(type="text", text=f"result:{name}")]

        wrapped = stack.wrap(handler)
        result = await wrapped("my_tool", {"key": "value"})

        assert len(result) == 1
        assert result[0].text == "result:my_tool"
        assert stack.metrics.total_calls == 1
        assert stack.metrics.error_count == 0
        assert stack.metrics.calls_by_tool["my_tool"] == 1

    @pytest.mark.asyncio
    async def test_wraps_error_call(self) -> None:
        stack = MiddlewareStack(enable_logging=False)

        async def handler(name: str, arguments: dict | None) -> list[TextContent]:
            raise ValueError("boom")

        wrapped = stack.wrap(handler)
        result = await wrapped("bad_tool", None)

        assert len(result) == 1
        assert "error" in result[0].text.lower()
        assert stack.metrics.total_calls == 1
        assert stack.metrics.error_count == 1

    @pytest.mark.asyncio
    async def test_tracks_multiple_tools(self) -> None:
        stack = MiddlewareStack(enable_logging=False)

        async def handler(name: str, arguments: dict | None) -> list[TextContent]:
            return [TextContent(type="text", text="ok")]

        wrapped = stack.wrap(handler)
        await wrapped("tool_a", None)
        await wrapped("tool_b", None)
        await wrapped("tool_a", None)

        assert stack.metrics.total_calls == 3
        assert stack.metrics.calls_by_tool["tool_a"] == 2
        assert stack.metrics.calls_by_tool["tool_b"] == 1

    @pytest.mark.asyncio
    async def test_measures_duration(self) -> None:
        stack = MiddlewareStack(enable_logging=False)

        async def handler(name: str, arguments: dict | None) -> list[TextContent]:
            return [TextContent(type="text", text="ok")]

        wrapped = stack.wrap(handler)
        await wrapped("tool", None)

        assert stack.metrics.total_duration_ms > 0


class TestSummarizeArgs:
    def test_none_args(self) -> None:
        assert _summarize_args(None) == "{}"

    def test_empty_args(self) -> None:
        assert _summarize_args({}) == "{}"

    def test_small_args(self) -> None:
        result = _summarize_args({"key": "value"})
        assert result == json.dumps({"key": "value"})

    def test_large_args_truncated(self) -> None:
        large = {"data": "x" * 300}
        result = _summarize_args(large, max_len=50)
        assert len(result) <= 53  # 50 + "..."
        assert result.endswith("...")


class TestMiddlewareStackLayers:
    @pytest.mark.asyncio
    async def test_single_layer_applied(self) -> None:
        """A layer's wrap() is called and its logic runs."""
        from mcp.types import TextContent
        call_log: list[str] = []

        class RecordLayer:
            def wrap(self, handler):
                async def wrapped(name, args):
                    call_log.append(f"before:{name}")
                    result = await handler(name, args)
                    call_log.append(f"after:{name}")
                    return result
                return wrapped

        async def base(name, args):
            return [TextContent(type="text", text="ok")]

        stack = MiddlewareStack(layers=[RecordLayer()])
        wrapped = stack.wrap(base)
        await wrapped("mytool", {})
        assert "before:mytool" in call_log
        assert "after:mytool" in call_log

    @pytest.mark.asyncio
    async def test_layers_applied_outermost_first(self) -> None:
        """First layer in list is outermost (runs first/last)."""
        from mcp.types import TextContent
        order: list[str] = []

        def make_layer(label: str):
            class L:
                def wrap(self, handler):
                    async def wrapped(name, args):
                        order.append(f"in:{label}")
                        r = await handler(name, args)
                        order.append(f"out:{label}")
                        return r
                    return wrapped
            return L()

        async def base(name, args):
            return [TextContent(type="text", text="ok")]

        stack = MiddlewareStack(layers=[make_layer("A"), make_layer("B")])
        await stack.wrap(base)("t", {})
        # A is outermost: A.in → B.in → base → B.out → A.out
        assert order == ["in:A", "in:B", "out:B", "out:A"]
