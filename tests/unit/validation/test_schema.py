"""Unit tests for JSON Schema validation."""

from __future__ import annotations

import pytest

from api2mcp.validation.exceptions import SchemaValidationError
from api2mcp.validation.schema import (
    check_required_fields,
    infer_string_fields,
    validate_against_schema,
)

_SCHEMA = {
    "type": "object",
    "properties": {
        "name": {"type": "string"},
        "count": {"type": "integer"},
        "active": {"type": "boolean"},
    },
    "required": ["name"],
}


# ---------------------------------------------------------------------------
# check_required_fields
# ---------------------------------------------------------------------------


def test_required_present_ok() -> None:
    check_required_fields({"name": "Alice"}, _SCHEMA)


def test_required_missing_raises() -> None:
    with pytest.raises(SchemaValidationError) as exc_info:
        check_required_fields({}, _SCHEMA, tool_name="myTool")
    assert "name" in exc_info.value.field
    assert exc_info.value.code == "schema_invalid"


def test_required_extra_fields_allowed() -> None:
    check_required_fields({"name": "Bob", "extra": "ok"}, _SCHEMA)


# ---------------------------------------------------------------------------
# validate_against_schema
# ---------------------------------------------------------------------------


def test_valid_input_passes() -> None:
    validate_against_schema({"name": "Alice", "count": 5}, _SCHEMA)


def test_wrong_type_raises() -> None:
    with pytest.raises(SchemaValidationError) as exc_info:
        validate_against_schema({"name": 123}, _SCHEMA)
    assert exc_info.value.code == "schema_invalid"


def test_missing_required_via_schema_raises() -> None:
    with pytest.raises(SchemaValidationError):
        validate_against_schema({}, _SCHEMA, tool_name="tool")


def test_empty_schema_allows_anything() -> None:
    validate_against_schema({"any": "value", "count": 99}, {})


def test_malformed_schema_logs_not_raises(caplog: pytest.LogCaptureFixture) -> None:
    import logging
    with caplog.at_level(logging.WARNING, logger="api2mcp.validation.schema"):
        # type must be a string, not an int — malformed schema
        validate_against_schema({"a": 1}, {"type": 999}, tool_name="bad_tool")
    # Should log a warning but not raise


def test_tool_name_appears_in_error_message() -> None:
    with pytest.raises(SchemaValidationError) as exc_info:
        validate_against_schema({"name": 123}, _SCHEMA, tool_name="myFunc")
    assert "myFunc" in str(exc_info.value)


# ---------------------------------------------------------------------------
# infer_string_fields
# ---------------------------------------------------------------------------


def test_infer_string_fields() -> None:
    result = infer_string_fields(_SCHEMA)
    assert result == {"name"}


def test_infer_string_fields_empty_schema() -> None:
    assert infer_string_fields({}) == set()


def test_infer_string_fields_mixed_types() -> None:
    schema = {
        "properties": {
            "a": {"type": "string"},
            "b": {"type": "integer"},
            "c": {"type": "string"},
        }
    }
    result = infer_string_fields(schema)
    assert result == {"a", "c"}
