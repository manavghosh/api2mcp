"""Unit tests for injection detection and HTML sanitization."""

from __future__ import annotations

import pytest

from api2mcp.validation.exceptions import InjectionDetectedError
from api2mcp.validation.sanitizer import (
    SanitizerConfig,
    check_string,
    sanitize_arguments,
    sanitize_html,
)

# ---------------------------------------------------------------------------
# Path traversal
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("payload", [
    "../etc/passwd",
    "..\\windows\\system32",
    "foo/../../../etc",
    "%2e%2e%2fetc",
])
def test_path_traversal_detected(payload: str) -> None:
    with pytest.raises(InjectionDetectedError) as exc_info:
        check_string(payload, field="path")
    assert exc_info.value.attack_type == "path traversal"


def test_path_traversal_disabled_allows() -> None:
    cfg = SanitizerConfig(check_path_traversal=False)
    result = check_string("../etc/passwd", field="path", config=cfg)
    assert result == "../etc/passwd"


def test_normal_path_allowed() -> None:
    result = check_string("documents/report.pdf", field="path")
    assert result == "documents/report.pdf"


# ---------------------------------------------------------------------------
# Command injection
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("payload", [
    "file; rm -rf /",
    "input | cat /etc/passwd",
    "`id`",
    "$(whoami)",
    "a && b",
    "a || b",
])
def test_command_injection_detected(payload: str) -> None:
    with pytest.raises(InjectionDetectedError) as exc_info:
        check_string(payload, field="cmd")
    assert exc_info.value.attack_type == "command injection"


def test_command_injection_disabled_allows() -> None:
    cfg = SanitizerConfig(check_command_injection=False)
    result = check_string("a | b", field="cmd", config=cfg)
    assert result == "a | b"


# ---------------------------------------------------------------------------
# SQL injection
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("payload", [
    "' OR '1'='1",
    "1; DROP TABLE users; --",
    "UNION SELECT * FROM users WHERE id=1",
    "admin'--",
])
def test_sql_injection_detected(payload: str) -> None:
    with pytest.raises(InjectionDetectedError) as exc_info:
        check_string(payload, field="query")
    assert exc_info.value.attack_type == "SQL injection"


def test_sql_injection_disabled_allows() -> None:
    cfg = SanitizerConfig(check_sql_injection=False)
    result = check_string("' OR '1'='1", field="q", config=cfg)
    assert result == "' OR '1'='1"


def test_normal_sql_query_name_allowed() -> None:
    # Just "select" as a word without FROM/WHERE context should be safe
    result = check_string("my_selection_field", field="q")
    assert result == "my_selection_field"


# ---------------------------------------------------------------------------
# XSS
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("payload", [
    "<script>alert(1)</script>",
    "javascript:void(0)",
    "<img src=x onerror=alert(1)>",
    "<iframe src='evil.com'>",
    "vbscript:msgbox(1)",
])
def test_xss_detected(payload: str) -> None:
    with pytest.raises(InjectionDetectedError) as exc_info:
        check_string(payload, field="html")
    assert exc_info.value.attack_type == "XSS"


def test_xss_disabled_allows() -> None:
    cfg = SanitizerConfig(check_xss=False)
    result = check_string("<script>x</script>", field="html", config=cfg)
    assert result == "<script>x</script>"


def test_benign_html_allowed() -> None:
    result = check_string("price < 100 and count > 0", field="text")
    assert result == "price < 100 and count > 0"


# ---------------------------------------------------------------------------
# HTML sanitization
# ---------------------------------------------------------------------------


def test_sanitize_html_escapes_entities() -> None:
    result = sanitize_html('<b>hello & "world"</b>')
    assert "<b>" not in result
    assert "&lt;" in result
    assert "&amp;" in result


def test_check_string_sanitize_html_mode() -> None:
    cfg = SanitizerConfig(
        check_xss=False,
        check_command_injection=False,
        check_sql_injection=False,
        check_path_traversal=False,
        sanitize_html=True,
    )
    result = check_string('<b>hello</b>', field="text", config=cfg)
    assert "<b>" not in result
    assert "&lt;" in result


# ---------------------------------------------------------------------------
# sanitize_arguments (recursive)
# ---------------------------------------------------------------------------


def test_sanitize_arguments_clean_input() -> None:
    args = {"name": "Alice", "count": 5}
    result = sanitize_arguments(args)
    assert result == args


def test_sanitize_arguments_nested_injection() -> None:
    with pytest.raises(InjectionDetectedError):
        sanitize_arguments({"user": {"name": "'; DROP TABLE--"}})


def test_sanitize_arguments_in_list() -> None:
    with pytest.raises(InjectionDetectedError):
        sanitize_arguments({"tags": ["ok", "../traversal"]})


def test_sanitize_arguments_does_not_mutate_input() -> None:
    args = {"name": "safe"}
    sanitize_arguments(args)
    assert args == {"name": "safe"}


def test_sanitize_arguments_non_string_passthrough() -> None:
    args = {"count": 42, "flag": True, "data": None}
    result = sanitize_arguments(args)
    assert result == args
