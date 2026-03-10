"""Unit tests for transport configuration (TASK-025, TASK-026)."""

import pytest

from api2mcp.runtime.transport import TransportConfig, TransportType


class TestTransportType:
    def test_enum_values(self) -> None:
        assert TransportType.STDIO == "stdio"
        assert TransportType.STREAMABLE_HTTP == "streamable_http"

    def test_enum_from_string(self) -> None:
        assert TransportType("stdio") == TransportType.STDIO
        assert TransportType("streamable_http") == TransportType.STREAMABLE_HTTP


class TestTransportConfig:
    def test_defaults(self) -> None:
        config = TransportConfig()
        assert config.transport_type == TransportType.STDIO
        assert config.host == "127.0.0.1"
        assert config.port == 8000
        assert config.path == "/mcp"
        assert config.json_response is False
        assert config.stateless is False
        assert config.extra == {}

    def test_stdio_factory(self) -> None:
        config = TransportConfig.stdio()
        assert config.transport_type == TransportType.STDIO

    def test_http_factory(self) -> None:
        config = TransportConfig.http(host="0.0.0.0", port=9000, path="/api/mcp")
        assert config.transport_type == TransportType.STREAMABLE_HTTP
        assert config.host == "0.0.0.0"
        assert config.port == 9000
        assert config.path == "/api/mcp"

    def test_http_factory_stateless(self) -> None:
        config = TransportConfig.http(stateless=True, json_response=True)
        assert config.stateless is True
        assert config.json_response is True

    def test_http_factory_defaults(self) -> None:
        config = TransportConfig.http()
        assert config.host == "127.0.0.1"
        assert config.port == 8000
        assert config.path == "/mcp"

    def test_extra_field(self) -> None:
        config = TransportConfig(extra={"timeout": 30})
        assert config.extra["timeout"] == 30
