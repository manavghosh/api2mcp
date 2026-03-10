"""Unit tests for MCPToolAdapter and schema conversion utilities."""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from pydantic import BaseModel

from api2mcp.orchestration.adapters.base import (
    MCPToolAdapter,
    _extract_text,
    _json_schema_to_pydantic,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_mcp_tool(
    name: str = "list_issues",
    description: str = "List issues",
    input_schema: dict[str, Any] | None = None,
) -> MagicMock:
    """Return a mock mcp.types.Tool."""
    tool = MagicMock()
    tool.name = name
    tool.description = description
    tool.inputSchema = input_schema if input_schema is not None else {
        "type": "object",
        "properties": {
            "owner": {"type": "string", "description": "Repo owner"},
            "repo": {"type": "string", "description": "Repo name"},
        },
        "required": ["owner", "repo"],
    }
    return tool


def _make_session(result_text: str = '{"items": []}', is_error: bool = False) -> AsyncMock:
    """Return a mock ClientSession whose call_tool returns text content."""
    content_item = MagicMock()
    content_item.text = result_text
    content_item.data = None

    call_result = MagicMock()
    call_result.isError = is_error
    call_result.content = [content_item]

    session = AsyncMock()
    session.call_tool = AsyncMock(return_value=call_result)
    return session


# ---------------------------------------------------------------------------
# _json_schema_to_pydantic
# ---------------------------------------------------------------------------


class TestJsonSchemaToPydantic:
    def test_required_fields_are_required(self) -> None:
        schema = {
            "properties": {"name": {"type": "string"}},
            "required": ["name"],
        }
        model = _json_schema_to_pydantic("mytool", schema)
        with pytest.raises(Exception):  # noqa: B017
            model()  # missing required field

    def test_optional_fields_default_to_none(self) -> None:
        schema = {
            "properties": {"label": {"type": "string"}},
        }
        model = _json_schema_to_pydantic("mytool", schema)
        instance = model()
        assert instance.label is None  # type: ignore[attr-defined]

    def test_string_maps_to_str(self) -> None:
        schema = {
            "properties": {"name": {"type": "string"}},
            "required": ["name"],
        }
        model = _json_schema_to_pydantic("t", schema)
        assert model.model_fields["name"].annotation is str

    def test_integer_maps_to_int(self) -> None:
        schema = {
            "properties": {"count": {"type": "integer"}},
            "required": ["count"],
        }
        model = _json_schema_to_pydantic("t", schema)
        assert model.model_fields["count"].annotation is int

    def test_number_maps_to_float(self) -> None:
        schema = {
            "properties": {"ratio": {"type": "number"}},
            "required": ["ratio"],
        }
        model = _json_schema_to_pydantic("t", schema)
        assert model.model_fields["ratio"].annotation is float

    def test_boolean_maps_to_bool(self) -> None:
        schema = {
            "properties": {"active": {"type": "boolean"}},
            "required": ["active"],
        }
        model = _json_schema_to_pydantic("t", schema)
        assert model.model_fields["active"].annotation is bool

    def test_array_maps_to_list(self) -> None:
        schema = {
            "properties": {"tags": {"type": "array"}},
            "required": ["tags"],
        }
        model = _json_schema_to_pydantic("t", schema)
        assert model.model_fields["tags"].annotation is list

    def test_object_maps_to_dict(self) -> None:
        schema = {
            "properties": {"metadata": {"type": "object"}},
            "required": ["metadata"],
        }
        model = _json_schema_to_pydantic("t", schema)
        assert model.model_fields["metadata"].annotation is dict

    def test_unknown_type_defaults_to_str(self) -> None:
        schema = {
            "properties": {"mystery": {"type": "unknown_type"}},
            "required": ["mystery"],
        }
        model = _json_schema_to_pydantic("t", schema)
        assert model.model_fields["mystery"].annotation is str

    def test_empty_schema_returns_valid_model(self) -> None:
        model = _json_schema_to_pydantic("empty", {})
        assert issubclass(model, BaseModel)
        # Can be instantiated with no args
        instance = model()
        assert instance is not None

    def test_model_name_incorporates_tool_name(self) -> None:
        model = _json_schema_to_pydantic("my_tool", {})
        assert "my_tool" in model.__name__

    def test_description_forwarded_to_field(self) -> None:
        schema = {
            "properties": {
                "owner": {"type": "string", "description": "The owner name"}
            },
            "required": ["owner"],
        }
        model = _json_schema_to_pydantic("t", schema)
        field_info = model.model_fields["owner"]
        assert field_info.description == "The owner name"


# ---------------------------------------------------------------------------
# _extract_text
# ---------------------------------------------------------------------------


class TestExtractText:
    def test_extracts_text_from_text_content(self) -> None:
        item = MagicMock()
        item.text = "hello"
        item.data = None
        assert _extract_text([item]) == "hello"

    def test_joins_multiple_items(self) -> None:
        a = MagicMock()
        a.text = "first"
        a.data = None
        b = MagicMock()
        b.text = "second"
        b.data = None
        assert _extract_text([a, b]) == "first\nsecond"

    def test_falls_back_to_data(self) -> None:
        item = MagicMock(spec=["data"])
        item.data = b"\xff\xfe"
        assert _extract_text([item]) != ""

    def test_empty_list_returns_empty_string(self) -> None:
        assert _extract_text([]) == ""


# ---------------------------------------------------------------------------
# MCPToolAdapter.from_mcp_tool
# ---------------------------------------------------------------------------


class TestMCPToolAdapterFromMCPTool:
    @pytest.mark.asyncio
    async def test_returns_structured_tool(self) -> None:
        from langchain_core.tools import StructuredTool

        session = _make_session()
        tool = _make_mcp_tool()
        structured = await MCPToolAdapter.from_mcp_tool(session, tool, "github")
        assert isinstance(structured, StructuredTool)

    @pytest.mark.asyncio
    async def test_tool_name_is_namespaced(self) -> None:
        session = _make_session()
        tool = _make_mcp_tool(name="list_issues")
        structured = await MCPToolAdapter.from_mcp_tool(session, tool, "github")
        assert structured.name == "github:list_issues"

    @pytest.mark.asyncio
    async def test_description_preserved(self) -> None:
        session = _make_session()
        tool = _make_mcp_tool(description="Lists open issues")
        structured = await MCPToolAdapter.from_mcp_tool(session, tool, "github")
        assert structured.description == "Lists open issues"

    @pytest.mark.asyncio
    async def test_fallback_description_when_none(self) -> None:
        session = _make_session()
        tool = _make_mcp_tool(description=None)  # type: ignore[arg-type]
        tool.description = None
        structured = await MCPToolAdapter.from_mcp_tool(session, tool, "github")
        assert "github" in structured.description
        assert "list_issues" in structured.description

    @pytest.mark.asyncio
    async def test_invocation_returns_text(self) -> None:
        session = _make_session('{"issues": []}')
        tool = _make_mcp_tool()
        structured = await MCPToolAdapter.from_mcp_tool(session, tool, "github")
        result = await structured.ainvoke({"owner": "user", "repo": "project"})
        assert result == '{"issues": []}'

    @pytest.mark.asyncio
    async def test_empty_schema_tool_is_callable(self) -> None:
        session = _make_session("ok")
        tool = _make_mcp_tool(input_schema={})
        structured = await MCPToolAdapter.from_mcp_tool(session, tool, "svc")
        result = await structured.ainvoke({})
        assert result == "ok"

    @pytest.mark.asyncio
    async def test_response_transformer_applied(self) -> None:
        session = _make_session("raw result")

        def upper(s: str) -> str:
            return s.upper()

        tool = _make_mcp_tool(input_schema={})
        structured = await MCPToolAdapter.from_mcp_tool(
            session, tool, "svc", response_transformer=upper
        )
        result = await structured.ainvoke({})
        assert result == "RAW RESULT"

    @pytest.mark.asyncio
    async def test_mcp_error_raises_runtime_error(self) -> None:
        session = _make_session("Something went wrong", is_error=True)
        tool = _make_mcp_tool(input_schema={})
        structured = await MCPToolAdapter.from_mcp_tool(session, tool, "svc")
        with pytest.raises(RuntimeError, match="error"):
            await structured.ainvoke({})


# ---------------------------------------------------------------------------
# MCPToolAdapter metrics
# ---------------------------------------------------------------------------


class TestAdapterMetrics:
    @pytest.mark.asyncio
    async def test_call_count_increments(self) -> None:
        session = _make_session()
        _mcp_tool = _make_mcp_tool(input_schema={})
        adapter = MCPToolAdapter(
            session=session,
            mcp_tool_name="list_issues",
            server_name="github",
            name="github:list_issues",
            description="List issues",
            args_schema=_json_schema_to_pydantic("list_issues", {}),
        )
        structured = adapter.to_structured_tool()

        await structured.ainvoke({})
        await structured.ainvoke({})
        assert adapter.call_count == 2

    @pytest.mark.asyncio
    async def test_avg_latency_is_nonnegative(self) -> None:
        session = _make_session()
        adapter = MCPToolAdapter(
            session=session,
            mcp_tool_name="ping",
            server_name="svc",
            name="svc:ping",
            description="Ping",
            args_schema=_json_schema_to_pydantic("ping", {}),
        )
        structured = adapter.to_structured_tool()
        await structured.ainvoke({})
        assert adapter.avg_latency_ms >= 0.0

    def test_avg_latency_zero_before_any_call(self) -> None:
        adapter = MCPToolAdapter(
            session=AsyncMock(),
            mcp_tool_name="x",
            server_name="s",
            name="s:x",
            description="x",
            args_schema=_json_schema_to_pydantic("x", {}),
        )
        assert adapter.avg_latency_ms == 0.0
        assert adapter.call_count == 0

    @pytest.mark.asyncio
    async def test_metrics_dict_keys(self) -> None:
        adapter = MCPToolAdapter(
            session=AsyncMock(),
            mcp_tool_name="x",
            server_name="s",
            name="s:x",
            description="x",
            args_schema=_json_schema_to_pydantic("x", {}),
        )
        m = adapter.metrics()
        assert set(m) == {
            "name",
            "server_name",
            "mcp_tool_name",
            "call_count",
            "avg_latency_ms",
            "total_latency_ms",
        }


# ---------------------------------------------------------------------------
# Timeout / retry
# ---------------------------------------------------------------------------


class TestAdapterRetry:
    @pytest.mark.asyncio
    async def test_timeout_raises_after_exhaustion(self) -> None:
        """When call_tool always times out, RuntimeError is raised after retries."""

        async def slow_call(*_: Any, **__: Any) -> None:
            await asyncio.sleep(10)

        session = AsyncMock()
        session.call_tool = slow_call

        adapter = MCPToolAdapter(
            session=session,
            mcp_tool_name="x",
            server_name="s",
            name="s:x",
            description="x",
            args_schema=_json_schema_to_pydantic("x", {}),
            timeout_seconds=0.01,
            retry_count=1,
        )
        structured = adapter.to_structured_tool()
        with pytest.raises((asyncio.TimeoutError, RuntimeError)):
            await structured.ainvoke({})
