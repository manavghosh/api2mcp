# SPDX-License-Identifier: MIT
"""MCP Server Runner — lifecycle management for generated MCP servers.

Provides MCPServerRunner that:
- Creates an MCP server from APISpec + MCPToolDefs (or wraps an existing Server)
- Supports stdio and Streamable HTTP transports
- Handles graceful shutdown with resource cleanup
- Integrates middleware, streaming, and health checks

Usage:
    # From APISpec (end-to-end: parse → generate → serve)
    runner = MCPServerRunner.from_api_spec(api_spec, tools)
    await runner.run_async()

    # From existing low-level Server
    runner = MCPServerRunner(server, config=TransportConfig.http(port=9000))
    await runner.run_async()

    # Synchronous entry point
    runner.run()
"""

from __future__ import annotations

import asyncio
import json
import logging
import signal
import sys
from typing import Any

import anyio
import httpx
from mcp.server.lowlevel import Server
from mcp.types import TextContent, Tool

from api2mcp.auth.base import AuthProvider, RequestContext
from api2mcp.core.exceptions import RuntimeException
from api2mcp.core.ir_schema import APISpec
from api2mcp.generators.tool import MCPToolDef
from api2mcp.pool.manager import ConnectionPoolManager
from api2mcp.runtime.health import HealthChecker
from api2mcp.runtime.middleware import MiddlewareStack
from api2mcp.runtime.streaming import error_result
from api2mcp.runtime.transport import TransportConfig, TransportType

logger = logging.getLogger(__name__)


class MCPServerRunner:
    """Manages the lifecycle of an MCP server.

    Args:
        server: The low-level MCP Server instance.
        config: Transport and server configuration.
        middleware: Optional middleware stack for tool calls.
        tools: Tool definitions (for health check reporting).
    """

    def __init__(
        self,
        server: Server,
        *,
        config: TransportConfig | None = None,
        middleware: MiddlewareStack | None = None,
        tools: list[MCPToolDef] | None = None,
        pool: ConnectionPoolManager | None = None,
    ) -> None:
        self.server = server
        self.config = config or TransportConfig.stdio()
        self.middleware = middleware or MiddlewareStack()
        self._tools = tools or []
        self._health = HealthChecker(
            server_name=server.name,
            tool_count=len(self._tools),
        )
        self._pool = pool
        self._shutdown_event: asyncio.Event | None = None

    @classmethod
    def from_api_spec(
        cls,
        api_spec: APISpec,
        tools: list[MCPToolDef],
        *,
        config: TransportConfig | None = None,
        middleware: MiddlewareStack | None = None,
        pool: ConnectionPoolManager | None = None,
        server_name: str | None = None,
        server_version: str | None = None,
        auth_provider: AuthProvider | None = None,
    ) -> MCPServerRunner:
        """Create a server runner directly from an APISpec and generated tools.

        This bypasses template-based code generation and creates a live MCP server
        from the IR + tool definitions.

        Args:
            api_spec: Parsed API specification.
            tools: Generated MCP tool definitions from ToolGenerator.
            config: Transport configuration.
            middleware: Optional middleware stack.
            server_name: Override server name (defaults to API title).
            server_version: Override version (defaults to API version).
        """
        name = server_name or api_spec.title
        version = server_version or api_spec.version

        server = Server(name, version=version)

        # Convert MCPToolDefs to MCP Tool objects
        mcp_tools = [
            Tool(
                name=t.name,
                description=t.description,
                inputSchema=t.input_schema,
            )
            for t in tools
        ]

        # Register tool listing handler
        @server.list_tools()
        async def list_tools() -> list[Tool]:
            return mcp_tools

        # Build tool dispatch table
        base_url = api_spec.base_url or (
            api_spec.servers[0].url if api_spec.servers else "http://localhost:8080"
        )
        tool_endpoints = {t.name: t for t in tools}

        # Register tool call handler (with middleware wrapping)
        mw = middleware or MiddlewareStack()

        async def _raw_call_tool(
            name: str, arguments: dict[str, Any] | None
        ) -> list[TextContent]:
            tool_def = tool_endpoints.get(name)
            if tool_def is None:
                return error_result(f"Unknown tool: {name}")
            return await _execute_tool(
                tool_def, arguments or {}, base_url,
                pool=pool,
                auth_provider=auth_provider,
            )

        wrapped_handler = mw.wrap(_raw_call_tool)

        @server.call_tool()
        async def call_tool(
            name: str, arguments: dict[str, Any] | None
        ) -> list[TextContent]:
            return await wrapped_handler(name, arguments)

        return cls(server, config=config, middleware=mw, tools=tools, pool=pool)

    @property
    def health(self) -> HealthChecker:
        """Access the health checker."""
        return self._health

    async def run_async(self) -> None:
        """Run the server asynchronously with the configured transport."""
        if self._shutdown_event is None:
            self._shutdown_event = asyncio.Event()

        if self._pool is not None:
            async with self._pool:
                await self._run_transport()
        else:
            await self._run_transport()

    async def _run_transport(self) -> None:
        """Dispatch to the configured transport."""
        if self.config.transport_type == TransportType.STDIO:
            await self._run_stdio()
        elif self.config.transport_type == TransportType.STREAMABLE_HTTP:
            await self._run_streamable_http()
        else:
            raise RuntimeException(
                f"Unsupported transport: {self.config.transport_type}",
                transport=str(self.config.transport_type),
            )

    def run(self) -> None:
        """Run the server synchronously (blocking entry point)."""
        try:
            anyio.run(self.run_async)
        except KeyboardInterrupt:
            logger.info("Server stopped by keyboard interrupt")

    async def shutdown(self) -> None:
        """Signal the server to shut down gracefully."""
        logger.info("Shutdown requested for server '%s'", self.server.name)
        if self._shutdown_event is not None:
            self._shutdown_event.set()

    async def _run_stdio(self) -> None:
        """Run the server over stdio transport."""
        from mcp.server.stdio import stdio_server

        logger.info(
            "Starting MCP server '%s' on stdio transport",
            self.server.name,
        )

        init_options = self.server.create_initialization_options()

        async with stdio_server() as (read_stream, write_stream):
            await self.server.run(read_stream, write_stream, init_options)

    async def _run_streamable_http(self) -> None:
        """Run the server over Streamable HTTP transport."""
        from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
        from starlette.applications import Starlette
        from starlette.requests import Request
        from starlette.responses import JSONResponse
        from starlette.routing import Route

        logger.info(
            "Starting MCP server '%s' on Streamable HTTP at %s:%d%s",
            self.server.name,
            self.config.host,
            self.config.port,
            self.config.path,
        )

        session_manager = StreamableHTTPSessionManager(
            app=self.server,
            json_response=self.config.json_response,
            stateless=self.config.stateless,
        )

        # Health check endpoint
        health_checker = self._health

        async def health_endpoint(request: Request) -> JSONResponse:
            status = health_checker.check()
            code = 200 if status.status == "healthy" else 503
            return JSONResponse(status.to_dict(), status_code=code)

        async def handle_mcp(scope: Any, receive: Any, send: Any) -> None:
            await session_manager.handle_request(scope, receive, send)

        app = Starlette(
            debug=False,
            routes=[
                Route("/health", health_endpoint, methods=["GET"]),
                Route(self.config.path, handle_mcp, methods=["GET", "POST", "DELETE"]),
            ],
        )

        import uvicorn

        config = uvicorn.Config(
            app,
            host=self.config.host,
            port=self.config.port,
            log_level=self.config.log_level,
        )
        server = uvicorn.Server(config)

        # Install signal handlers for graceful shutdown
        self._install_signal_handlers(server)

        async with session_manager.run():
            await server.serve()

    def _install_signal_handlers(self, uvicorn_server: Any) -> None:
        """Install signal handlers for graceful shutdown."""
        loop = asyncio.get_running_loop()

        def _signal_handler() -> None:
            logger.info("Received shutdown signal")
            uvicorn_server.should_exit = True
            if self._shutdown_event is not None:
                self._shutdown_event.set()

        if sys.platform != "win32":
            for sig in (signal.SIGINT, signal.SIGTERM):
                loop.add_signal_handler(sig, _signal_handler)


async def _execute_tool(
    tool_def: MCPToolDef,
    arguments: dict[str, Any],
    base_url: str,
    *,
    pool: ConnectionPoolManager | None = None,
    auth_provider: AuthProvider | None = None,
) -> list[TextContent]:
    """Execute a tool by making the actual HTTP request to the target API.

    Args:
        tool_def: The tool definition with endpoint info.
        arguments: The tool call arguments.
        base_url: The API base URL.
        pool: Optional :class:`ConnectionPoolManager` for persistent connections.
            When ``None``, a new :class:`httpx.AsyncClient` is created per call.
        auth_provider: Optional :class:`AuthProvider` whose credentials are
            merged into the outgoing request headers/params/cookies.
    """
    endpoint = tool_def.endpoint

    # Build path with parameter substitution
    path = endpoint.path
    for param in endpoint.parameters:
        if param.location.value == "path" and param.name in arguments:
            path = path.replace(f"{{{param.name}}}", str(arguments[param.name]))

    # Build query parameters
    params = {}
    for param in endpoint.parameters:
        if param.location.value == "query" and param.name in arguments:
            params[param.name] = arguments[param.name]

    # Build headers
    headers: dict[str, str] = {}
    for param in endpoint.parameters:
        if param.location.value == "header" and param.name in arguments:
            headers[param.name] = str(arguments[param.name])

    # Build request body
    json_body: dict[str, Any] | None = None
    if tool_def.body_param_names:
        json_body = {
            k: arguments[k] for k in tool_def.body_param_names if k in arguments
        }

    # Apply authentication credentials
    if auth_provider is not None:
        ctx = RequestContext()
        await auth_provider.apply(ctx)
        headers.update(ctx.headers)
        params.update(ctx.params)
        if ctx.cookies:
            cookie_str = "; ".join(f"{k}={v}" for k, v in ctx.cookies.items())
            headers["Cookie"] = cookie_str

    method = endpoint.method.value.lower()

    try:
        if pool is not None:
            # Use pooled client — connection reuse + retry handled by pool
            response = await pool.request(
                base_url,
                method.upper(),
                path,
                params=params or None,
                headers=headers or None,
                json=json_body or None,
            )
        else:
            # Fallback: ephemeral client (original behaviour)
            timeout = getattr(tool_def, "timeout", None)
            async with httpx.AsyncClient(base_url=base_url, timeout=timeout) as client:
                response = await client.request(
                    method,
                    path,
                    params=params or None,
                    headers=headers or None,
                    json=json_body or None,
                )

        response.raise_for_status()

        if response.headers.get("content-type", "").startswith("application/json"):
            text = json.dumps(response.json(), indent=2)
        else:
            text = response.text or f"Status: {response.status_code}"

    except httpx.HTTPStatusError as exc:
        text = json.dumps({
            "error": f"HTTP {exc.response.status_code}",
            "detail": exc.response.text[:500],
        })
    except httpx.RequestError as exc:
        text = json.dumps({"error": f"Request failed: {exc}"})

    return [TextContent(type="text", text=text)]
