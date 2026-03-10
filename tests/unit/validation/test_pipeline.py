"""Unit tests for the validation pipeline and middleware."""

from __future__ import annotations

import json

import pytest
from mcp.types import TextContent

from api2mcp.validation.exceptions import (
    InjectionDetectedError,
    SchemaValidationError,
    SizeExceededError,
)
from api2mcp.validation.limits import SizeLimits
from api2mcp.validation.pipeline import (
    ValidationConfig,
    ValidationMiddleware,
    validate_tool_input,
)

_SCHEMA = {
    "type": "object",
    "properties": {"name": {"type": "string"}, "count": {"type": "integer"}},
    "required": ["name"],
}


# ---------------------------------------------------------------------------
# validate_tool_input
# ---------------------------------------------------------------------------


def test_pipeline_valid_input() -> None:
    result = validate_tool_input("myTool", {"name": "Alice"}, _SCHEMA)
    assert result["name"] == "Alice"


def test_pipeline_none_args_treated_as_empty() -> None:
    schema_no_required: dict = {"type": "object", "properties": {}}
    result = validate_tool_input("t", None, schema_no_required)
    assert result == {}


def test_pipeline_missing_required_raises() -> None:
    with pytest.raises(SchemaValidationError):
        validate_tool_input("t", {}, _SCHEMA)


def test_pipeline_injection_raises() -> None:
    with pytest.raises(InjectionDetectedError):
        validate_tool_input("t", {"name": "../etc/passwd"}, _SCHEMA)


def test_pipeline_size_check_raises() -> None:
    cfg = ValidationConfig(size_limits=SizeLimits(max_payload_bytes=10))
    with pytest.raises(SizeExceededError):
        validate_tool_input("t", {"name": "x" * 100}, _SCHEMA, config=cfg)


def test_pipeline_disabled_bypasses_all() -> None:
    cfg = ValidationConfig(enabled=False)
    result = validate_tool_input(
        "t", {"name": "'; DROP TABLE--"}, _SCHEMA, config=cfg
    )
    assert result["name"] == "'; DROP TABLE--"


def test_pipeline_returns_sanitized_copy() -> None:
    args = {"name": "Alice"}
    result = validate_tool_input("t", args, _SCHEMA)
    assert result is not args  # New dict


# ---------------------------------------------------------------------------
# ValidationMiddleware
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_middleware_passes_valid_input() -> None:
    async def handler(_name: str, args: dict | None) -> list[TextContent]:
        return [TextContent(type="text", text=f"ok:{args}")]

    schemas = {"myTool": _SCHEMA}
    middleware = ValidationMiddleware(schemas)
    wrapped = middleware.wrap(handler)

    result = await wrapped("myTool", {"name": "Bob", "count": 3})
    assert "ok:" in result[0].text


@pytest.mark.asyncio
async def test_middleware_returns_error_on_invalid_default() -> None:
    async def handler(_name: str, _args: dict | None) -> list[TextContent]:
        return [TextContent(type="text", text="should not reach")]

    schemas = {"t": _SCHEMA}
    middleware = ValidationMiddleware(schemas)  # raise_on_error=False by default
    wrapped = middleware.wrap(handler)

    result = await wrapped("t", {})  # missing required "name"
    assert len(result) == 1
    data = json.loads(result[0].text)
    assert "error" in data


@pytest.mark.asyncio
async def test_middleware_raises_when_configured() -> None:
    async def handler(_name: str, _args: dict | None) -> list[TextContent]:
        return []

    schemas = {"t": _SCHEMA}
    cfg = ValidationConfig(raise_on_error=True)
    middleware = ValidationMiddleware(schemas, config=cfg)
    wrapped = middleware.wrap(handler)

    with pytest.raises(SchemaValidationError):
        await wrapped("t", {})


@pytest.mark.asyncio
async def test_middleware_unknown_tool_uses_empty_schema() -> None:
    """Unknown tools get validated against a permissive empty schema."""
    async def handler(_name: str, _args: dict | None) -> list[TextContent]:
        return [TextContent(type="text", text="ok")]

    schemas: dict = {}
    middleware = ValidationMiddleware(schemas)
    wrapped = middleware.wrap(handler)

    result = await wrapped("unknown_tool", {"any": "value"})
    assert result[0].text == "ok"


@pytest.mark.asyncio
async def test_middleware_injection_blocked_returns_error() -> None:
    async def handler(_name: str, _args: dict | None) -> list[TextContent]:
        return [TextContent(type="text", text="ok")]

    schemas = {"t": _SCHEMA}
    middleware = ValidationMiddleware(schemas)
    wrapped = middleware.wrap(handler)

    result = await wrapped("t", {"name": "<script>alert(1)</script>"})
    data = json.loads(result[0].text)
    assert "xss" in data.get("code", "").lower() or "error" in data
