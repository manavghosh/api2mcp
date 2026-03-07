"""Unit tests for MCPServerRunner (TASK-021 through TASK-028)."""

import pytest
from mcp.server.lowlevel import Server
from typing import Any

from api2mcp.core.ir_schema import (
    APISpec,
    Endpoint,
    HttpMethod,
    Parameter,
    ParameterLocation,
    RequestBody,
    SchemaRef,
    SchemaType,
    ServerInfo,
)
from api2mcp.generators.tool import MCPToolDef
from api2mcp.runtime.middleware import MiddlewareStack
from api2mcp.runtime.server import MCPServerRunner
from api2mcp.runtime.transport import TransportConfig, TransportType


# --- Fixtures ---


def _simple_api_spec() -> APISpec:
    """Create a minimal API spec for testing."""
    return APISpec(
        title="Test API",
        version="1.0.0",
        description="A test API",
        base_url="https://api.example.com",
        servers=[ServerInfo(url="https://api.example.com")],
        source_format="openapi3.0",
        endpoints=[
            Endpoint(
                path="/items",
                method=HttpMethod.GET,
                operation_id="listItems",
                summary="List items",
                parameters=[
                    Parameter(
                        name="limit",
                        location=ParameterLocation.QUERY,
                        schema=SchemaRef(type=SchemaType.INTEGER),
                        required=False,
                    ),
                ],
            ),
            Endpoint(
                path="/items/{id}",
                method=HttpMethod.GET,
                operation_id="getItem",
                summary="Get item by ID",
                parameters=[
                    Parameter(
                        name="id",
                        location=ParameterLocation.PATH,
                        schema=SchemaRef(type=SchemaType.STRING),
                        required=True,
                    ),
                ],
            ),
        ],
    )


def _simple_tools() -> list[MCPToolDef]:
    """Create tool defs matching the simple API spec."""
    spec = _simple_api_spec()
    return [
        MCPToolDef(
            name="list_items",
            description="List items",
            input_schema={
                "type": "object",
                "properties": {
                    "limit": {"type": "integer"},
                },
            },
            endpoint=spec.endpoints[0],
        ),
        MCPToolDef(
            name="get_item",
            description="Get item by ID",
            input_schema={
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                },
                "required": ["id"],
            },
            endpoint=spec.endpoints[1],
        ),
    ]


class TestMCPServerRunnerInit:
    def test_from_server_instance(self) -> None:
        server = Server("test_server", version="1.0")
        runner = MCPServerRunner(server)
        assert runner.server.name == "test_server"
        assert runner.config.transport_type == TransportType.STDIO

    def test_from_server_with_config(self) -> None:
        server = Server("test_server")
        config = TransportConfig.http(port=9000)
        runner = MCPServerRunner(server, config=config)
        assert runner.config.transport_type == TransportType.STREAMABLE_HTTP
        assert runner.config.port == 9000

    def test_health_checker_initialized(self) -> None:
        server = Server("my_server")
        runner = MCPServerRunner(server, tools=_simple_tools())
        status = runner.health.check()
        assert status.server_name == "my_server"
        assert status.tool_count == 2


class TestMCPServerRunnerFromAPISpec:
    def test_creates_runner(self) -> None:
        spec = _simple_api_spec()
        tools = _simple_tools()
        runner = MCPServerRunner.from_api_spec(spec, tools)
        assert runner.server.name == "Test API"

    def test_custom_server_name(self) -> None:
        spec = _simple_api_spec()
        tools = _simple_tools()
        runner = MCPServerRunner.from_api_spec(
            spec, tools, server_name="custom_name"
        )
        assert runner.server.name == "custom_name"

    def test_uses_middleware(self) -> None:
        spec = _simple_api_spec()
        tools = _simple_tools()
        mw = MiddlewareStack(enable_logging=False)
        runner = MCPServerRunner.from_api_spec(spec, tools, middleware=mw)
        assert runner.middleware is mw

    def test_uses_custom_config(self) -> None:
        spec = _simple_api_spec()
        tools = _simple_tools()
        config = TransportConfig.http(port=5555)
        runner = MCPServerRunner.from_api_spec(spec, tools, config=config)
        assert runner.config.port == 5555


class TestMCPServerRunnerHealth:
    def test_health_accessible(self) -> None:
        server = Server("test")
        runner = MCPServerRunner(server)
        assert runner.health is not None
        assert runner.health.check().status == "healthy"


class TestExceptions:
    def test_runtime_exception_fields(self) -> None:
        from api2mcp.core.exceptions import RuntimeException

        exc = RuntimeException("test error", transport="stdio")
        assert str(exc) == "test error"
        assert exc.transport == "stdio"

    def test_transport_exception(self) -> None:
        from api2mcp.core.exceptions import TransportException

        exc = TransportException("connection failed", transport="http")
        assert exc.transport == "http"

    def test_shutdown_exception(self) -> None:
        from api2mcp.core.exceptions import ShutdownException

        exc = ShutdownException("timeout")
        assert str(exc) == "timeout"


@pytest.mark.asyncio
async def test_run_async_starts_and_closes_pool() -> None:
    """Pool's __aenter__ and __aexit__ are called inside run_async."""
    from unittest.mock import AsyncMock

    runner = MCPServerRunner.from_api_spec(_simple_api_spec(), _simple_tools())

    mock_pool = AsyncMock()
    mock_pool.__aenter__ = AsyncMock(return_value=mock_pool)
    mock_pool.__aexit__ = AsyncMock(return_value=False)
    runner._pool = mock_pool

    async def _fake_transport() -> None:
        pass

    runner._run_transport = _fake_transport  # type: ignore[method-assign]

    await runner.run_async()

    mock_pool.__aenter__.assert_awaited_once()
    mock_pool.__aexit__.assert_awaited_once()


@pytest.mark.asyncio
async def test_execute_tool_applies_auth_headers() -> None:
    """AuthProvider credentials are merged into the outgoing httpx request."""
    from unittest.mock import AsyncMock, MagicMock, patch

    from api2mcp.auth.base import AuthProvider, RequestContext
    from api2mcp.runtime.server import _execute_tool

    class BearerProvider(AuthProvider):
        async def apply(self, ctx: RequestContext) -> None:
            ctx.headers["Authorization"] = "Bearer test-token-123"

    # Build a minimal tool_def using the same pattern as existing fixtures
    spec = _simple_api_spec()
    tool_def = MCPToolDef(
        name="list_items",
        description="List items",
        input_schema={"type": "object", "properties": {}},
        endpoint=spec.endpoints[0],  # GET /items
    )

    captured_headers: dict[str, str] = {}

    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.headers = {"content-type": "application/json"}
    mock_response.json.return_value = []

    async def fake_request(method: str, path: str, **kwargs: Any) -> MagicMock:
        captured_headers.update(kwargs.get("headers") or {})
        return mock_response

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.request = fake_request

    with patch("httpx.AsyncClient", return_value=mock_client):
        result = await _execute_tool(
            tool_def,
            {},
            "https://api.example.com",
            auth_provider=BearerProvider(),
        )

    assert captured_headers.get("Authorization") == "Bearer test-token-123"
    assert isinstance(result, list)
    assert len(result) == 1
