"""Tests for helpful secrets backend error messages."""
from __future__ import annotations
import pytest


def test_unknown_backend_raises_value_error():
    """Creating an unknown backend raises ValueError."""
    try:
        from api2mcp.secrets.factory import build_secret_provider
        with pytest.raises(ValueError, match="Unknown secrets backend"):
            build_secret_provider("nonexistent_xyz_backend_12345")
    except ImportError:
        from api2mcp.secrets import factory
        for fn_name in ["create_backend", "get_backend", "make_backend", "from_config", "build_secret_provider"]:
            fn = getattr(factory, fn_name, None)
            if fn is not None:
                with pytest.raises((ValueError, KeyError, TypeError)):
                    fn({"backend": "nonexistent_xyz_backend_12345"})
                break


def test_unknown_backend_message_includes_name():
    """Error message includes the invalid backend name."""
    from api2mcp.secrets.factory import build_secret_provider
    with pytest.raises(ValueError, match="nonexistent_xyz_backend_12345"):
        build_secret_provider("nonexistent_xyz_backend_12345")


def test_unknown_backend_message_includes_valid_options():
    """Error message lists valid backend options."""
    from api2mcp.secrets.factory import build_secret_provider
    with pytest.raises(ValueError, match="env"):
        build_secret_provider("nonexistent_xyz_backend_12345")


def test_factory_importable():
    from api2mcp.secrets import factory
    assert factory is not None
