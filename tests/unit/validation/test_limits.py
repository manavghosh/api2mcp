"""Unit tests for size-limit enforcement."""

from __future__ import annotations

import pytest

from api2mcp.validation.exceptions import SizeExceededError
from api2mcp.validation.limits import SizeLimits, check_field_sizes, check_payload_size

# ---------------------------------------------------------------------------
# check_payload_size
# ---------------------------------------------------------------------------


def test_payload_within_limit() -> None:
    check_payload_size({"key": "value"})  # no exception


def test_payload_exceeds_limit() -> None:
    big = {"data": "x" * 2_000_000}
    with pytest.raises(SizeExceededError) as exc_info:
        check_payload_size(big, SizeLimits(max_payload_bytes=100))
    assert exc_info.value.field == "<payload>"
    assert exc_info.value.actual > 100


def test_payload_exact_limit_passes() -> None:
    data = {"k": "v"}
    import json
    size = len(json.dumps(data).encode())
    check_payload_size(data, SizeLimits(max_payload_bytes=size))


# ---------------------------------------------------------------------------
# check_field_sizes — strings
# ---------------------------------------------------------------------------


def test_string_within_limit() -> None:
    check_field_sizes({"name": "hello"})


def test_string_exceeds_limit() -> None:
    with pytest.raises(SizeExceededError) as exc_info:
        check_field_sizes(
            {"name": "x" * 200},
            SizeLimits(max_string_length=100),
        )
    assert "name" in exc_info.value.field


def test_nested_string_checked() -> None:
    with pytest.raises(SizeExceededError) as exc_info:
        check_field_sizes(
            {"obj": {"inner": "y" * 200}},
            SizeLimits(max_string_length=50),
        )
    assert "inner" in exc_info.value.field


# ---------------------------------------------------------------------------
# check_field_sizes — arrays
# ---------------------------------------------------------------------------


def test_array_within_limit() -> None:
    check_field_sizes({"items": list(range(10))})


def test_array_exceeds_limit() -> None:
    with pytest.raises(SizeExceededError) as exc_info:
        check_field_sizes(
            {"items": list(range(50))},
            SizeLimits(max_array_items=10),
        )
    assert "items" in exc_info.value.field


# ---------------------------------------------------------------------------
# check_field_sizes — objects
# ---------------------------------------------------------------------------


def test_object_keys_within_limit() -> None:
    check_field_sizes({"meta": {str(i): i for i in range(5)}})


def test_object_keys_exceed_limit() -> None:
    with pytest.raises(SizeExceededError):
        check_field_sizes(
            {"meta": {str(i): i for i in range(100)}},
            SizeLimits(max_object_keys=10),
        )


def test_size_exceeded_error_fields() -> None:
    err = SizeExceededError(field="body", actual=999, limit=100)
    assert err.actual == 999
    assert err.limit == 100
    assert err.code == "size_exceeded"
    assert "body" in str(err)
