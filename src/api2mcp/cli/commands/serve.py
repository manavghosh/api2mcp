# SPDX-License-Identifier: MIT
"""``api2mcp serve`` command — start a generated MCP server."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from typing import IO, TYPE_CHECKING, Any

import click

from api2mcp.cli import output
from api2mcp.cli.config import load_config, merge_config
from api2mcp.core.exceptions import API2MCPError, ParseException
from api2mcp.runtime.middleware import MiddlewareStack
from api2mcp.runtime.transport import TransportConfig

if TYPE_CHECKING:
    from api2mcp.auth.base import AuthProvider
    from api2mcp.pool.manager import ConnectionPoolManager


def _build_middleware_stack(
    effective: dict[str, Any],
) -> tuple[MiddlewareStack, AuthProvider | None, ConnectionPoolManager | None]:
    """Build a :class:`MiddlewareStack`, optional auth provider, and optional pool.

    Reads the ``auth``, ``validation``, ``rate_limit``, ``cache``,
    ``concurrency``, ``circuit_breaker``, and ``pool`` sections from *effective*
    and constructs the corresponding objects using their default constructors.
    Returns a 3-tuple ``(stack, auth_provider | None, pool_manager | None)``.
    """
    layers: list[Any] = []

    # --- Auth provider ---
    auth_provider: Any = None
    auth_cfg: dict[str, Any] = effective.get("auth") or {}
    auth_type = auth_cfg.get("type", "none").lower()

    if auth_type == "api_key":
        from api2mcp.auth.providers.api_key import APIKeyProvider  # noqa: PLC0415

        auth_provider = APIKeyProvider(
            key_value=auth_cfg.get("value", ""),
            key_name=auth_cfg.get("key_name", "X-Api-Key"),
            location=auth_cfg.get("location", "header"),
        )
    elif auth_type == "bearer":
        from api2mcp.auth.providers.bearer import BearerTokenProvider  # noqa: PLC0415

        auth_provider = BearerTokenProvider(token=auth_cfg.get("value", ""))
    elif auth_type == "basic":
        from api2mcp.auth.providers.basic import BasicAuthProvider  # noqa: PLC0415

        auth_provider = BasicAuthProvider(
            username=auth_cfg.get("username", ""),
            password=auth_cfg.get("password", ""),
        )

    # --- Validation middleware ---
    if effective.get("validation"):
        from api2mcp.validation.pipeline import ValidationMiddleware  # noqa: PLC0415

        layers.append(ValidationMiddleware(schemas={}))

    # --- Rate limit middleware ---
    if effective.get("rate_limit"):
        from api2mcp.ratelimit.middleware import RateLimitMiddleware  # noqa: PLC0415

        layers.append(RateLimitMiddleware())

    # --- Cache middleware ---
    if effective.get("cache"):
        from api2mcp.cache.middleware import CacheMiddleware  # noqa: PLC0415

        layers.append(CacheMiddleware())

    # --- Concurrency middleware ---
    if effective.get("concurrency"):
        from api2mcp.concurrency.middleware import ConcurrencyMiddleware  # noqa: PLC0415

        layers.append(ConcurrencyMiddleware())

    # --- Circuit breaker middleware ---
    if effective.get("circuit_breaker"):
        from api2mcp.circuitbreaker.middleware import CircuitBreakerMiddleware  # noqa: PLC0415

        layers.append(CircuitBreakerMiddleware())

    stack = MiddlewareStack(layers=layers)

    # --- Connection pool ---
    pool_manager: Any = None
    if effective.get("pool"):
        from api2mcp.pool.manager import ConnectionPoolManager  # noqa: PLC0415

        pool_manager = ConnectionPoolManager()

    return stack, auth_provider, pool_manager


def _check_tls_warning(
    host: str,
    transport: str,
    tls_warning: bool = True,
    stderr: IO[str] | None = None,
) -> None:
    """Print a TLS warning to stderr when serving unencrypted on a public interface."""
    if not tls_warning:
        return
    if transport != "http":
        return
    if host not in ("0.0.0.0", "::"):
        return
    out = stderr or sys.stderr
    out.write(
        "\n\u26a0  WARNING: MCP server is bound to 0.0.0.0 without TLS.\n"
        "   All traffic including auth tokens is plaintext.\n"
        "   For production, use a TLS reverse proxy (nginx, Caddy, AWS ALB).\n"
        "   To silence: set 'tls_warning: false' in .api2mcp.yaml\n\n"
    )


@click.command("serve")
@click.argument(
    "server_dir",
    default=".",
    type=click.Path(file_okay=False, path_type=Path),
)
@click.option(
    "--host",
    default=None,
    help="Bind host for HTTP transport (default: 0.0.0.0).",
)
@click.option(
    "--port",
    "-p",
    default=None,
    type=int,
    help="Bind port for HTTP transport (default: 8000).",
)
@click.option(
    "--transport",
    type=click.Choice(["stdio", "http"], case_sensitive=False),
    default=None,
    help="Transport to use: stdio (default) or http.",
)
@click.option(
    "--log-level",
    type=click.Choice(
        ["critical", "error", "warning", "info", "debug"], case_sensitive=False
    ),
    default=None,
    help="Logging verbosity (default: info).",
)
@click.option(
    "--config",
    "-c",
    "config_file",
    default=None,
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    help="Path to .api2mcp.yaml config file.",
)
@click.option(
    "--watch",
    "-w",
    "watch",
    is_flag=True,
    default=False,
    help="Enable hot reload: restart server automatically when spec or code changes.",
)
def serve_cmd(
    server_dir: Path,
    host: str | None,
    port: int | None,
    transport: str | None,
    log_level: str | None,
    config_file: Path | None,
    watch: bool,
) -> None:
    """Start the MCP server in SERVER_DIR.

    SERVER_DIR should contain a spec.yaml (or openapi.yaml) file previously
    generated by ``api2mcp generate``, or any OpenAPI spec file.

    \b
    Examples:
      api2mcp serve ./generated
      api2mcp serve ./generated --transport http --port 9000
      api2mcp serve .  # uses spec.yaml in cwd
      api2mcp serve . --watch  # hot reload on file changes (dev mode)
    """
    cfg = load_config(config_file)
    effective = merge_config(
        cfg,
        host=host,
        port=port,
        transport=transport,
        log_level=log_level,
    )

    resolved_transport = effective.get("transport", "stdio").lower()
    resolved_host = effective.get("host", "0.0.0.0")
    resolved_port = int(effective.get("port", 8000))
    _check_tls_warning(
        host=resolved_host,
        transport=resolved_transport,
        tls_warning=cfg.get("tls_warning", True),
    )

    # Locate spec file
    spec_file = _find_spec_file(server_dir)
    if spec_file is None:
        output.error(
            f"No spec file found in [bold]{server_dir}[/bold]. "
            "Expected spec.yaml, openapi.yaml, or openapi.json."
        )
        sys.exit(1)

    if resolved_transport == "http":
        output.header(
            "API2MCP · Serve",
            f"Spec: {spec_file}  |  http://{resolved_host}:{resolved_port}/mcp",
        )
    else:
        output.header("API2MCP · Serve", f"Spec: {spec_file}  |  stdio transport")

    # --- Parse spec ---
    with output.spinner("Loading API specification…"):
        try:
            from api2mcp.parsers.openapi import OpenAPIParser

            parser = OpenAPIParser()
            api_spec = asyncio.run(parser.parse(spec_file))
        except ParseException as exc:
            output.error(f"Failed to parse specification: {exc}")
            sys.exit(1)
        except API2MCPError as exc:
            output.error(str(exc))
            sys.exit(1)

    # --- Generate tools ---
    with output.spinner("Building MCP tool registry…"):
        from api2mcp.generators.tool import ToolGenerator

        generator = ToolGenerator()
        tools = generator.generate(api_spec)

    # Emit PRE_SERVE hook
    try:
        from api2mcp.plugins import get_hook_manager
        from api2mcp.plugins.hooks import PRE_SERVE
        get_hook_manager().emit_sync(PRE_SERVE, api_spec=api_spec, tools=tools)
    except Exception:  # noqa: BLE001
        pass  # plugins are optional

    output.success(
        f"Serving [bold]{api_spec.title}[/bold] v{api_spec.version} "
        f"with {len(tools)} tool(s)"
    )

    # --- Build transport config ---
    if resolved_transport == "http":
        config = TransportConfig.http(
            host=resolved_host,
            port=resolved_port,
        )
        output.info(
            f"MCP endpoint: [bold]http://{resolved_host}:{resolved_port}/mcp[/bold]"
        )
        output.info(
            f"Health check: http://{resolved_host}:{resolved_port}/health"
        )
    else:
        config = TransportConfig.stdio()

    # --- Start server (normal or hot-reload mode) ---
    if watch:
        output.info("[bold]Hot reload enabled[/bold] — watching for file changes…")
        from api2mcp.hotreload.restart import HotReloadServer

        hot_server = HotReloadServer(
            spec_path=spec_file,
            output_dir=server_dir,
            transport=resolved_transport,
            host=resolved_host,
            port=resolved_port,
        )
        try:
            asyncio.run(hot_server.run())
        except KeyboardInterrupt:
            output.info("Server stopped.")
        return

    # --- Build middleware stack, auth provider, and connection pool ---
    middleware_stack, auth_provider, pool_manager = _build_middleware_stack(effective)

    from api2mcp.runtime.server import MCPServerRunner  # noqa: PLC0415

    runner = MCPServerRunner.from_api_spec(
        api_spec,
        tools,
        config=config,
        middleware=middleware_stack,
        pool=pool_manager,
        auth_provider=auth_provider,
    )

    try:
        runner.run()
    except KeyboardInterrupt:
        output.info("Server stopped.")


def _find_spec_file(directory: Path) -> Path | None:
    """Return the first spec file found in *directory*."""
    candidates = ["spec.yaml", "openapi.yaml", "openapi.yml", "openapi.json"]
    for name in candidates:
        path = directory / name
        if path.is_file():
            return path
    return None
