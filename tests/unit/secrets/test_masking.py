"""Unit tests for secret log masking."""

from __future__ import annotations

import logging

import pytest

from api2mcp.secrets.masking import (
    MaskingFilter,
    SecretRegistry,
    mask,
)


@pytest.fixture(autouse=True)
def fresh_registry(monkeypatch: pytest.MonkeyPatch) -> SecretRegistry:
    """Each test gets a clean SecretRegistry (doesn't mutate the global)."""
    reg = SecretRegistry()
    monkeypatch.setattr(
        "api2mcp.secrets.masking.SecretRegistry._instance", reg
    )
    return reg


# ---------------------------------------------------------------------------
# SecretRegistry
# ---------------------------------------------------------------------------


def test_register_and_mask() -> None:
    reg = SecretRegistry()
    reg.register("supersecret")
    assert reg.mask("token=supersecret here") == "token=*** here"


def test_mask_no_secrets() -> None:
    reg = SecretRegistry()
    assert reg.mask("hello world") == "hello world"


def test_register_too_short_ignored() -> None:
    reg = SecretRegistry()
    reg.register("abc")
    assert reg.mask("abc is not masked") == "abc is not masked"


def test_register_empty_ignored() -> None:
    reg = SecretRegistry()
    reg.register("")
    assert reg.mask("empty") == "empty"


def test_multiple_secrets_all_masked() -> None:
    reg = SecretRegistry()
    reg.register("token_a")
    reg.register("token_b")
    text = "use token_a and token_b together"
    result = reg.mask(text)
    assert "token_a" not in result
    assert "token_b" not in result
    assert "***" in result


def test_longer_secret_masked_before_substring() -> None:
    reg = SecretRegistry()
    reg.register("ghp_longer_secret")
    reg.register("ghp_longer")
    result = reg.mask("value=ghp_longer_secret")
    # The full longer secret should be masked, not leave a partial match
    assert "ghp_longer_secret" not in result


def test_unregister() -> None:
    reg = SecretRegistry()
    reg.register("mysecret")
    reg.unregister("mysecret")
    assert reg.mask("mysecret") == "mysecret"


def test_clear() -> None:
    reg = SecretRegistry()
    reg.register("alpha")
    reg.register("beta")
    reg.clear()
    assert reg.mask("alpha beta") == "alpha beta"


def test_global_singleton_is_same_instance() -> None:
    a = SecretRegistry.global_instance()
    b = SecretRegistry.global_instance()
    assert a is b


# ---------------------------------------------------------------------------
# MaskingFilter
# ---------------------------------------------------------------------------


def test_masking_filter_masks_message() -> None:
    reg = SecretRegistry()
    reg.register("s3cr3t")
    filt = MaskingFilter(registry=reg)

    record = logging.LogRecord(
        name="test", level=logging.INFO,
        pathname="", lineno=0,
        msg="password is s3cr3t",
        args=None, exc_info=None,
    )
    filt.filter(record)
    assert "s3cr3t" not in record.msg
    assert "***" in record.msg


def test_masking_filter_masks_args() -> None:
    reg = SecretRegistry()
    reg.register("token_xyz")
    filt = MaskingFilter(registry=reg)

    record = logging.LogRecord(
        name="test", level=logging.INFO,
        pathname="", lineno=0,
        msg="value=%s",
        args=("token_xyz",), exc_info=None,
    )
    filt.filter(record)
    assert record.args is not None
    assert "token_xyz" not in str(record.args)


def test_masking_filter_returns_true() -> None:
    reg = SecretRegistry()
    filt = MaskingFilter(registry=reg)
    record = logging.LogRecord(
        name="test", level=logging.INFO,
        pathname="", lineno=0,
        msg="hello", args=None, exc_info=None,
    )
    assert filt.filter(record) is True


def test_masking_filter_none_args_ok() -> None:
    reg = SecretRegistry()
    reg.register("secret")
    filt = MaskingFilter(registry=reg)
    record = logging.LogRecord(
        name="test", level=logging.INFO,
        pathname="", lineno=0,
        msg="no args", args=None, exc_info=None,
    )
    filt.filter(record)  # should not raise


# ---------------------------------------------------------------------------
# mask() convenience
# ---------------------------------------------------------------------------


def test_mask_convenience_function() -> None:
    reg = SecretRegistry()
    reg.register("password123")
    result = mask("using password123 in string", registry=reg)
    assert "password123" not in result
    assert "***" in result
