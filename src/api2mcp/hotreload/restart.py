# SPDX-License-Identifier: MIT
"""Graceful restart logic for hot reload — F6.2.

:class:`HotReloadServer` wraps a :class:`~api2mcp.runtime.server.MCPServerRunner`
factory and a :class:`~api2mcp.hotreload.watcher.FileWatcher`.  When the
watcher emits a :class:`~api2mcp.hotreload.watcher.ChangeEvent`, the server is
gracefully shut down, the spec is re-parsed and re-generated, and the server
is restarted.

State preservation notes:

- In-flight HTTP requests are drained before shutdown (best-effort).
- Conversation state held in LangGraph checkpointers is on-disk and survives
  restarts automatically — no special handling is required here.
- Active stdio connections cannot survive a process restart; clients must
  reconnect.

Usage::

    from api2mcp.hotreload.restart import HotReloadServer

    server = HotReloadServer(
        spec_path=Path("openapi.yaml"),
        output_dir=Path("generated"),
        transport="http",
        host="0.0.0.0",
        port=8000,
    )
    await server.run()  # blocks until Ctrl-C
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from api2mcp.hotreload.watcher import ChangeEvent, FileWatcher

logger = logging.getLogger(__name__)

# How long (seconds) to wait for in-flight requests before hard-stopping.
_DRAIN_TIMEOUT: float = 5.0


class HotReloadServer:
    """Development server that restarts on file changes.

    Args:
        spec_path:   Path to the API spec file (OpenAPI / Swagger).
        output_dir:  Directory for generated server files.
        transport:   ``"stdio"`` or ``"http"``.
        host:        Bind host for HTTP transport.
        port:        Bind port for HTTP transport.
        watch_paths: Extra directories / files to monitor in addition to
                     *spec_path* and *output_dir*.
        poll_interval_ms: File watcher poll frequency in milliseconds.
    """

    def __init__(
        self,
        spec_path: Path,
        output_dir: Path,
        *,
        transport: str = "stdio",
        host: str = "0.0.0.0",
        port: int = 8000,
        watch_paths: list[Path] | None = None,
        poll_interval_ms: int = 300,
    ) -> None:
        self.spec_path = spec_path
        self.output_dir = output_dir
        self.transport = transport
        self.host = host
        self.port = port
        self._watch_paths: list[Path] = watch_paths or []
        self._poll_interval_ms = poll_interval_ms

        self._server_task: asyncio.Task[None] | None = None
        self._restart_count: int = 0

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    async def run(self) -> None:
        """Start the server and watch for file changes.

        Blocks until a ``KeyboardInterrupt`` or ``asyncio.CancelledError``
        terminates the loop.
        """
        watcher = FileWatcher(
            paths=[self.output_dir, self.spec_path.parent] + self._watch_paths,
            poll_interval_ms=self._poll_interval_ms,
        )

        logger.info("HotReloadServer: starting initial server")
        await self._start_server()

        try:
            async for event in watcher.watch():
                await self._handle_change(event)
        except (KeyboardInterrupt, asyncio.CancelledError):
            logger.info("HotReloadServer: shutting down")
        finally:
            watcher.stop()
            await self._stop_server()

    # ------------------------------------------------------------------
    # Change handling
    # ------------------------------------------------------------------

    async def _handle_change(self, event: ChangeEvent) -> None:
        """React to a file change by triggering a restart."""
        logger.info(
            "HotReloadServer: change detected — %s %s",
            event.change_type.value,
            event.path,
        )

        needs_reparse = (
            event.path == self.spec_path
            or event.path.suffix in (".yaml", ".yml", ".json")
        )

        if needs_reparse:
            logger.info("HotReloadServer: spec/config changed — re-parsing before restart")
            await self._regenerate()

        await self._restart_server()

    async def _regenerate(self) -> None:
        """Re-parse the spec and regenerate output files."""
        try:

            from api2mcp.generators.tool import ToolGenerator
            from api2mcp.parsers.openapi import OpenAPIParser

            parser = OpenAPIParser()
            api_spec = await parser.parse(self.spec_path)
            generator = ToolGenerator()
            tools = generator.generate(api_spec)

            self.output_dir.mkdir(parents=True, exist_ok=True)
            from api2mcp.cli.commands.generate import _write_server_module
            _write_server_module(self.output_dir, api_spec=api_spec, tools=tools, server_name=None)
            logger.info(
                "HotReloadServer: regenerated %d tool(s) in %s",
                len(tools),
                self.output_dir,
            )
        except Exception as exc:  # noqa: BLE001
            logger.error("HotReloadServer: regeneration failed: %s", exc)

    # ------------------------------------------------------------------
    # Server lifecycle
    # ------------------------------------------------------------------

    async def _start_server(self) -> None:
        """Launch the MCP server as an asyncio background task."""
        self._server_task = asyncio.create_task(
            self._run_server(), name=f"mcp-server-{self._restart_count}"
        )
        self._restart_count += 1
        logger.debug(
            "HotReloadServer: started server task (restart #%d)", self._restart_count
        )

    async def _stop_server(self) -> None:
        """Cancel the current server task and wait for it to finish."""
        if self._server_task is None or self._server_task.done():
            return
        self._server_task.cancel()
        try:
            await asyncio.wait_for(
                asyncio.shield(self._server_task),
                timeout=_DRAIN_TIMEOUT,
            )
        except (TimeoutError, asyncio.CancelledError) as exc:
            logger.debug("Server drain timeout/cancelled: %s", exc)
        logger.debug("HotReloadServer: server task stopped")

    async def _restart_server(self) -> None:
        """Stop the current server and start a fresh one."""
        logger.info("HotReloadServer: restarting server…")
        await self._stop_server()
        await self._start_server()
        logger.info("HotReloadServer: server restarted (restart #%d)", self._restart_count)

    async def _run_server(self) -> None:
        """Build and run the MCP server (runs until cancelled)."""
        try:
            from api2mcp.generators.tool import ToolGenerator
            from api2mcp.parsers.openapi import OpenAPIParser
            from api2mcp.runtime.server import MCPServerRunner
            from api2mcp.runtime.transport import TransportConfig

            parser = OpenAPIParser()
            api_spec = await parser.parse(self.spec_path)
            generator = ToolGenerator()
            tools = generator.generate(api_spec)

            if self.transport == "http":
                config = TransportConfig.http(
                    host=self.host,
                    port=self.port,
                )
            else:
                config = TransportConfig.stdio()

            runner = MCPServerRunner.from_api_spec(api_spec, tools, config=config)
            await asyncio.to_thread(runner.run)
        except asyncio.CancelledError:
            logger.debug("HotReloadServer._run_server: cancelled")
            raise
        except Exception as exc:  # noqa: BLE001
            logger.error("HotReloadServer._run_server: error: %s", exc)
