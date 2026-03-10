"""Integration tests for MCP runtime via stdio transport (TASK-029, TASK-030).

Tests the full client-server interaction: initialize → list tools → call tool → shutdown.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from mcp.types import TextContent

from api2mcp.core.ir_schema import (
    APISpec,
    Endpoint,
    HttpMethod,
    Parameter,
    ParameterLocation,
    SchemaRef,
    SchemaType,
    ServerInfo,
)
from api2mcp.generators.tool import MCPToolDef
from api2mcp.runtime.middleware import MiddlewareStack
from api2mcp.runtime.server import MCPServerRunner, _execute_tool


def _test_spec() -> APISpec:
    """Create a test API spec."""
    return APISpec(
        title="Test API",
        version="1.0.0",
        base_url="https://api.test.com",
        servers=[ServerInfo(url="https://api.test.com")],
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
        ],
    )


def _test_tools() -> list[MCPToolDef]:
    """Create test tool definitions."""
    spec = _test_spec()
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
    ]


def _make_mock_response(
    status_code: int = 200,
    json_data: object = None,
    text: str = "",
    content_type: str = "application/json",
    raise_for_status_error: Exception | None = None,
) -> MagicMock:
    """Create a properly mocked httpx Response."""
    response = MagicMock()
    response.status_code = status_code
    response.headers = {"content-type": content_type}
    response.text = text
    if json_data is not None:
        response.json.return_value = json_data
    if raise_for_status_error:
        response.raise_for_status.side_effect = raise_for_status_error
    else:
        response.raise_for_status.return_value = None
    return response


def _make_mock_client(response: MagicMock | None = None, error: Exception | None = None) -> AsyncMock:
    """Create a properly mocked httpx.AsyncClient context manager."""
    client = AsyncMock()
    if error:
        client.request.side_effect = error
    elif response:
        client.request.return_value = response
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)
    return client


class TestServerCreation:
    """Test that from_api_spec creates a fully functional server."""

    def test_creates_server_with_correct_name(self) -> None:
        runner = MCPServerRunner.from_api_spec(_test_spec(), _test_tools())
        assert runner.server.name == "Test API"

    def test_server_has_capabilities(self) -> None:
        runner = MCPServerRunner.from_api_spec(_test_spec(), _test_tools())
        init_options = runner.server.create_initialization_options()
        assert init_options.server_name == "Test API"
        assert init_options.capabilities is not None
        assert init_options.capabilities.tools is not None


class TestToolExecution:
    """Test the tool execution pipeline with mocked HTTP."""

    @pytest.mark.asyncio
    async def test_execute_tool_success(self) -> None:
        """Test that _execute_tool makes correct HTTP request and returns result."""
        tool = _test_tools()[0]
        response = _make_mock_response(json_data=[{"id": 1, "name": "Item 1"}])
        client = _make_mock_client(response)

        with patch("api2mcp.runtime.server.httpx") as mock_httpx:
            mock_httpx.AsyncClient.return_value = client
            mock_httpx.HTTPStatusError = httpx.HTTPStatusError
            mock_httpx.RequestError = httpx.RequestError

            result = await _execute_tool(tool, {"limit": 10}, "https://api.test.com")

        assert len(result) == 1
        assert result[0].type == "text"
        parsed = json.loads(result[0].text)
        assert isinstance(parsed, list)
        assert parsed[0]["name"] == "Item 1"

        client.request.assert_called_once_with(
            "get",
            "/items",
            params={"limit": 10},
            headers=None,
            json=None,
        )

    @pytest.mark.asyncio
    async def test_execute_tool_http_error(self) -> None:
        """Test that HTTP errors are caught and returned as error messages."""
        tool = _test_tools()[0]

        mock_resp = _make_mock_response(status_code=500, text="Internal Server Error")
        error = httpx.HTTPStatusError("500", request=MagicMock(), response=mock_resp)
        mock_resp.raise_for_status.side_effect = error

        client = _make_mock_client(mock_resp)

        with patch("api2mcp.runtime.server.httpx") as mock_httpx:
            mock_httpx.AsyncClient.return_value = client
            mock_httpx.HTTPStatusError = httpx.HTTPStatusError
            mock_httpx.RequestError = httpx.RequestError

            result = await _execute_tool(tool, {}, "https://api.test.com")

        assert len(result) == 1
        parsed = json.loads(result[0].text)
        assert "error" in parsed
        assert "500" in parsed["error"]

    @pytest.mark.asyncio
    async def test_execute_tool_request_error(self) -> None:
        """Test that connection errors are handled gracefully."""
        tool = _test_tools()[0]
        client = _make_mock_client(error=httpx.RequestError("Connection refused"))

        with patch("api2mcp.runtime.server.httpx") as mock_httpx:
            mock_httpx.AsyncClient.return_value = client
            mock_httpx.HTTPStatusError = httpx.HTTPStatusError
            mock_httpx.RequestError = httpx.RequestError

            result = await _execute_tool(tool, {}, "https://api.test.com")

        assert len(result) == 1
        parsed = json.loads(result[0].text)
        assert "error" in parsed
        assert "Connection refused" in parsed["error"]

    @pytest.mark.asyncio
    async def test_execute_tool_text_response(self) -> None:
        """Test handling of non-JSON responses."""
        tool = _test_tools()[0]
        response = _make_mock_response(
            content_type="text/plain",
            text="Hello World",
        )
        client = _make_mock_client(response)

        with patch("api2mcp.runtime.server.httpx") as mock_httpx:
            mock_httpx.AsyncClient.return_value = client
            mock_httpx.HTTPStatusError = httpx.HTTPStatusError
            mock_httpx.RequestError = httpx.RequestError

            result = await _execute_tool(tool, {}, "https://api.test.com")

        assert len(result) == 1
        assert result[0].text == "Hello World"


class TestMiddlewareIntegration:
    """Test middleware wrapping in the full server pipeline."""

    @pytest.mark.asyncio
    async def test_middleware_tracks_calls(self) -> None:
        mw = MiddlewareStack(enable_logging=False)

        async def handler(name: str, arguments: dict | None) -> list[TextContent]:
            return [TextContent(type="text", text="ok")]

        wrapped = mw.wrap(handler)
        await wrapped("test_tool", {"key": "val"})

        assert mw.metrics.total_calls == 1
        assert mw.metrics.calls_by_tool["test_tool"] == 1
        assert mw.metrics.total_duration_ms > 0

    @pytest.mark.asyncio
    async def test_middleware_catches_errors(self) -> None:
        mw = MiddlewareStack(enable_logging=False)

        async def bad_handler(name: str, arguments: dict | None) -> list[TextContent]:
            raise RuntimeError("handler exploded")

        wrapped = mw.wrap(bad_handler)
        result = await wrapped("bad", None)

        assert mw.metrics.error_count == 1
        assert len(result) == 1
        assert "error" in result[0].text.lower()


class TestPathParameterSubstitution:
    """Test that path parameters are correctly substituted in tool execution."""

    @pytest.mark.asyncio
    async def test_path_params_substituted(self) -> None:
        spec = APISpec(
            title="Test",
            version="1.0",
            base_url="https://api.test.com",
            endpoints=[
                Endpoint(
                    path="/items/{item_id}/details",
                    method=HttpMethod.GET,
                    operation_id="getItemDetails",
                    parameters=[
                        Parameter(
                            name="item_id",
                            location=ParameterLocation.PATH,
                            schema=SchemaRef(type=SchemaType.STRING),
                            required=True,
                        ),
                    ],
                ),
            ],
        )

        tool = MCPToolDef(
            name="get_item_details",
            description="Get item details",
            input_schema={
                "type": "object",
                "properties": {"item_id": {"type": "string"}},
                "required": ["item_id"],
            },
            endpoint=spec.endpoints[0],
        )

        response = _make_mock_response(json_data={"id": "abc", "name": "Test Item"})
        client = _make_mock_client(response)

        with patch("api2mcp.runtime.server.httpx") as mock_httpx:
            mock_httpx.AsyncClient.return_value = client
            mock_httpx.HTTPStatusError = httpx.HTTPStatusError
            mock_httpx.RequestError = httpx.RequestError

            await _execute_tool(tool, {"item_id": "abc"}, "https://api.test.com")

        call_args = client.request.call_args
        assert call_args[0][1] == "/items/abc/details"

    @pytest.mark.asyncio
    async def test_header_params_passed(self) -> None:
        """Test that header parameters are correctly passed."""
        spec = APISpec(
            title="Test",
            version="1.0",
            base_url="https://api.test.com",
            endpoints=[
                Endpoint(
                    path="/data",
                    method=HttpMethod.GET,
                    operation_id="getData",
                    parameters=[
                        Parameter(
                            name="X-Custom-Header",
                            location=ParameterLocation.HEADER,
                            schema=SchemaRef(type=SchemaType.STRING),
                            required=True,
                        ),
                    ],
                ),
            ],
        )

        tool = MCPToolDef(
            name="get_data",
            description="Get data",
            input_schema={
                "type": "object",
                "properties": {"X-Custom-Header": {"type": "string"}},
            },
            endpoint=spec.endpoints[0],
        )

        response = _make_mock_response(json_data={"result": "ok"})
        client = _make_mock_client(response)

        with patch("api2mcp.runtime.server.httpx") as mock_httpx:
            mock_httpx.AsyncClient.return_value = client
            mock_httpx.HTTPStatusError = httpx.HTTPStatusError
            mock_httpx.RequestError = httpx.RequestError

            await _execute_tool(
                tool, {"X-Custom-Header": "my-value"}, "https://api.test.com"
            )

        call_args = client.request.call_args
        assert call_args.kwargs["headers"] == {"X-Custom-Header": "my-value"}
