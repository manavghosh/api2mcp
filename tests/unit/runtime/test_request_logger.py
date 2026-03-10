"""Tests for request/response logging with field redaction."""
from __future__ import annotations
import pytest


def test_redact_token_field():
    from api2mcp.runtime.request_logger import redact_params
    params = {"token": "secret123", "query": "hello"}
    result = redact_params(params)
    assert result["token"] == "[REDACTED]"
    assert result["query"] == "hello"


def test_redact_password_field():
    from api2mcp.runtime.request_logger import redact_params
    params = {"password": "hunter2", "username": "alice"}
    result = redact_params(params)
    assert result["password"] == "[REDACTED]"
    assert result["username"] == "alice"


def test_redact_api_key_field():
    from api2mcp.runtime.request_logger import redact_params
    params = {"api_key": "sk-abc123", "limit": 10}
    result = redact_params(params)
    assert result["api_key"] == "[REDACTED]"
    assert result["limit"] == 10


def test_non_sensitive_unchanged():
    from api2mcp.runtime.request_logger import redact_params
    params = {"user_id": "123", "action": "list", "page": 1}
    result = redact_params(params)
    assert result == params


def test_redact_nested_dict():
    from api2mcp.runtime.request_logger import redact_params
    params = {"auth": {"token": "secret_token", "type": "bearer"}}
    result = redact_params(params)
    assert result["auth"]["token"] == "[REDACTED]"
    assert result["auth"]["type"] == "bearer"


def test_redact_secret_field():
    from api2mcp.runtime.request_logger import redact_params
    params = {"client_secret": "my_secret_value", "scope": "read"}
    result = redact_params(params)
    assert result["client_secret"] == "[REDACTED]"


def test_log_tool_call_returns_float():
    from api2mcp.runtime.request_logger import log_tool_call
    t = log_tool_call("test_tool", {"param": "value"})
    assert isinstance(t, float)
    assert t > 0


def test_log_tool_response_does_not_raise():
    from api2mcp.runtime.request_logger import log_tool_call, log_tool_response
    t = log_tool_call("test_tool", {})
    log_tool_response("test_tool", t, status="ok", response_size=100)  # should not raise


def test_redact_does_not_mutate_input():
    from api2mcp.runtime.request_logger import redact_params
    original = {"password": "secret", "name": "alice"}
    _ = redact_params(original)
    assert original["password"] == "secret"  # original unchanged
