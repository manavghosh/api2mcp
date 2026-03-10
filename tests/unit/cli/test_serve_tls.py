"""Tests for serve command TLS warning."""
from __future__ import annotations
import io
from api2mcp.cli.commands.serve import _check_tls_warning  # type: ignore[reportAttributeAccessIssue]


def test_tls_warning_shown_for_0000_http():
    err = io.StringIO()
    _check_tls_warning(host="0.0.0.0", transport="http", tls_warning=True, stderr=err)
    assert err.getvalue() != "", "Expected TLS warning output"
    assert "WARNING" in err.getvalue() or "plaintext" in err.getvalue().lower()


def test_tls_warning_suppressed_for_stdio():
    err = io.StringIO()
    _check_tls_warning(host="0.0.0.0", transport="stdio", tls_warning=True, stderr=err)
    assert err.getvalue() == ""


def test_tls_warning_suppressed_when_disabled():
    err = io.StringIO()
    _check_tls_warning(host="0.0.0.0", transport="http", tls_warning=False, stderr=err)
    assert err.getvalue() == ""


def test_tls_warning_suppressed_for_localhost():
    err = io.StringIO()
    _check_tls_warning(host="127.0.0.1", transport="http", tls_warning=True, stderr=err)
    assert err.getvalue() == ""


def test_tls_warning_shown_for_double_colon():
    """IPv6 wildcard :: also triggers the warning."""
    err = io.StringIO()
    _check_tls_warning(host="::", transport="http", tls_warning=True, stderr=err)
    assert err.getvalue() != ""
