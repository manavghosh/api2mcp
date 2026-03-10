# SPDX-License-Identifier: MIT
"""MCP Tool Registry — central discovery and access for tools across MCP servers.

Maintains a flat namespace of colon-namespaced tools (``server:tool``) built
from one or more :class:`~mcp.client.session.ClientSession` instances or
lazily from :class:`ServerConfig` subprocess definitions.

Usage (session-based)::

    registry = MCPToolRegistry()
    await registry.register_server("github", github_session)
    await registry.register_server("jira", jira_session)
    all_tools = registry.get_tools()

Usage (config-based / lazy)::

    registry = MCPToolRegistry()
    await registry.register_server_config(
        ServerConfig(name="github", command="npx", args=["-y", "@github/mcp-server"])
    )
    await registry.connect_all()       # establishes subprocess connections
    tools = registry.get_tools(category="read")
    await registry.close()             # shuts down subprocesses

Pattern filtering::

    tools = registry.get_tools(pattern="github:list_*")
    tool  = registry.get_tool("github:list_issues")
    result = await tool.ainvoke({"owner": "user", "repo": "project"})
"""

from __future__ import annotations

import contextlib
import fnmatch
import logging
from dataclasses import dataclass, field
from typing import Any

from langchain_core.tools import StructuredTool

from api2mcp.orchestration.adapters.base import MCPToolAdapter, _json_schema_to_pydantic

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Category inference
# ---------------------------------------------------------------------------

_READ_PREFIXES = ("get", "list", "read", "fetch", "search", "find", "query", "describe")
_WRITE_PREFIXES = (
    "create",
    "post",
    "put",
    "patch",
    "update",
    "delete",
    "remove",
    "add",
    "set",
    "send",
    "submit",
    "push",
    "publish",
)


def _infer_category(namespaced_name: str) -> str:
    """Infer ``"read"``, ``"write"``, or ``"other"`` from a namespaced tool name.

    Uses the tool portion after the colon separator.

    Args:
        namespaced_name: Colon-namespaced name, e.g. ``"github:list_issues"``.
    """
    _, _, tool_part = namespaced_name.partition(":")
    lower = tool_part.lower()

    if any(lower.startswith(p) for p in _READ_PREFIXES):
        return "read"
    if any(lower.startswith(p) for p in _WRITE_PREFIXES):
        return "write"
    return "other"


# ---------------------------------------------------------------------------
# Server configuration (for lazy subprocess connections)
# ---------------------------------------------------------------------------


@dataclass
class ServerConfig:
    """Configuration for a subprocess-based MCP server connection.

    Used with :meth:`MCPToolRegistry.register_server_config` to register a
    server without immediately connecting.  Call
    :meth:`MCPToolRegistry.connect_server` or
    :meth:`MCPToolRegistry.connect_all` to establish the connection lazily.

    Args:
        name: Logical server identifier (used as namespace prefix).
        command: Executable to launch (e.g. ``"npx"``, ``"python"``).
        args: Arguments passed to *command*.
        env: Extra environment variables for the subprocess.
        category: Optional server-level category label (default ``"general"``).
    """

    name: str
    command: str
    args: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)
    category: str = "general"


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


class MCPToolRegistry:
    """Central registry for MCP tools across multiple servers.

    Supports two registration modes:

    1. **Session-based** (eager): pass an already-active
       :class:`~mcp.client.session.ClientSession` to
       :meth:`register_server`.  The caller owns session lifecycle.

    2. **Config-based** (lazy): pass a :class:`ServerConfig` to
       :meth:`register_server_config`, then call :meth:`connect_server` /
       :meth:`connect_all` to establish subprocess connections managed
       internally.  Call :meth:`close` to clean up.

    Tool names use colon namespacing::

        "github:list_issues"
        "jira:create_ticket"

    Args:
        default_timeout: Per-call timeout forwarded to every adapter.
        default_retry_count: Retry count forwarded to every adapter.
    """

    def __init__(
        self,
        *,
        default_timeout: float = 30.0,
        default_retry_count: int = 3,
    ) -> None:
        self._default_timeout = default_timeout
        self._default_retry_count = default_retry_count
        # server_name → ClientSession
        self._sessions: dict[str, Any] = {}
        # namespaced_name → StructuredTool
        self._tools: dict[str, StructuredTool] = {}
        # namespaced_name → MCPToolAdapter (for usage stats)
        self._adapters: dict[str, MCPToolAdapter] = {}
        # server_name → [namespaced_names]
        self._server_tool_names: dict[str, list[str]] = {}
        # server_name → ServerConfig (for lazy connections)
        self._configs: dict[str, ServerConfig] = {}
        # manages subprocess lifecycles for config-based connections
        self._exit_stack: contextlib.AsyncExitStack = contextlib.AsyncExitStack()

    # ------------------------------------------------------------------
    # Async context manager
    # ------------------------------------------------------------------

    async def __aenter__(self) -> "MCPToolRegistry":
        await self._exit_stack.__aenter__()
        return self

    async def __aexit__(self, *args: Any) -> None:
        await self._exit_stack.__aexit__(*args)

    # ------------------------------------------------------------------
    # Config-based (lazy) registration
    # ------------------------------------------------------------------

    async def register_server_config(self, config: ServerConfig) -> None:
        """Register a :class:`ServerConfig` without connecting.

        The actual subprocess connection is deferred to
        :meth:`connect_server` or :meth:`connect_all`.

        Args:
            config: Server configuration to store.
        """
        self._configs[config.name] = config
        logger.debug("Registered config for server '%s'", config.name)

    async def connect_server(self, name: str) -> Any:
        """Establish a subprocess connection for a registered config.

        Launches the subprocess described by the stored
        :class:`ServerConfig`, creates a
        :class:`~mcp.client.session.ClientSession`, initialises the
        protocol, and calls :meth:`register_server` to discover tools.

        If the server is already connected, returns the existing session.

        Args:
            name: Server name matching a previously registered
                :class:`ServerConfig`.

        Returns:
            The active :class:`~mcp.client.session.ClientSession`.

        Raises:
            ValueError: If no config is registered under *name*.
            ImportError: If the ``mcp`` package is not installed.
        """
        if name not in self._configs:
            raise ValueError(
                f"No ServerConfig registered for '{name}'. "
                "Call register_server_config() first."
            )
        if name in self._sessions:
            logger.debug("Server '%s' already connected, reusing session", name)
            return self._sessions[name]

        config = self._configs[name]

        try:
            from mcp import ClientSession, StdioServerParameters
            from mcp.client.stdio import stdio_client
        except ImportError as exc:  # pragma: no cover
            raise ImportError(
                "The 'mcp' package is required for subprocess connections. "
                "Install it with: pip install mcp"
            ) from exc

        server_params = StdioServerParameters(
            command=config.command,
            args=config.args,
            env=config.env if config.env else None,
        )

        read, write = await self._exit_stack.enter_async_context(
            stdio_client(server_params)
        )
        session: Any = await self._exit_stack.enter_async_context(
            ClientSession(read, write)
        )
        await session.initialize()
        await self.register_server(name, session)
        logger.info("Connected to server '%s' (command=%s)", name, config.command)
        return session

    async def connect_all(self) -> None:
        """Connect all registered :class:`ServerConfig` instances.

        Skips servers that are already connected.  Errors from individual
        servers are logged and re-raised immediately.
        """
        for name in list(self._configs):
            if name not in self._sessions:
                await self.connect_server(name)

    # ------------------------------------------------------------------
    # Session-based (eager) registration
    # ------------------------------------------------------------------

    async def register_server(
        self,
        server_name: str,
        session: Any,  # mcp.client.session.ClientSession
        *,
        timeout_seconds: float | None = None,
        retry_count: int | None = None,
    ) -> list[str]:
        """Discover all tools from *session* and register them under *server_name*.

        Calls ``session.list_tools()`` once and converts every returned tool
        into a :class:`~langchain_core.tools.StructuredTool`.

        Args:
            server_name: Logical server identifier (namespace prefix).
            session: Active MCP ClientSession.
            timeout_seconds: Per-adapter timeout override (defaults to
                :attr:`default_timeout`).
            retry_count: Per-adapter retry count override (defaults to
                :attr:`default_retry_count`).

        Returns:
            List of registered colon-namespaced tool names.
        """
        timeout = timeout_seconds if timeout_seconds is not None else self._default_timeout
        retries = retry_count if retry_count is not None else self._default_retry_count

        self._sessions[server_name] = session
        list_result = await session.list_tools()
        mcp_tools = list_result.tools

        registered: list[str] = []
        for mcp_tool in mcp_tools:
            schema: dict[str, Any] = mcp_tool.inputSchema if mcp_tool.inputSchema else {}
            args_schema = _json_schema_to_pydantic(mcp_tool.name, schema)
            namespaced_name = f"{server_name}:{mcp_tool.name}"
            description = (
                mcp_tool.description
                or f"MCP tool '{mcp_tool.name}' from server '{server_name}'"
            )

            adapter = MCPToolAdapter(
                session=session,
                mcp_tool_name=mcp_tool.name,
                server_name=server_name,
                name=namespaced_name,
                description=description,
                args_schema=args_schema,
                timeout_seconds=timeout,
                retry_count=retries,
            )
            self._adapters[namespaced_name] = adapter
            self._tools[namespaced_name] = adapter.to_structured_tool()
            registered.append(namespaced_name)
            logger.debug("Registered tool '%s'", namespaced_name)

        self._server_tool_names[server_name] = registered
        logger.info(
            "Registered %d tool(s) from server '%s'", len(registered), server_name
        )
        return registered

    def register_tool(
        self,
        server_name: str,
        tool: StructuredTool,
    ) -> str:
        """Manually register a pre-built :class:`~langchain_core.tools.StructuredTool`.

        Useful for testing or when the tool is built outside the registry.

        Args:
            server_name: Logical server identifier (namespace prefix).
            tool: The StructuredTool to register.

        Returns:
            The colon-namespaced name used in the registry.
        """
        if ":" in tool.name:
            namespaced = tool.name
        else:
            namespaced = f"{server_name}:{tool.name}"

        self._tools[namespaced] = tool
        self._server_tool_names.setdefault(server_name, []).append(namespaced)
        return namespaced

    def unregister_server(self, server_name: str) -> bool:
        """Remove all tools, adapters, and the session for *server_name*.

        Note: Subprocess connections established via :meth:`connect_server`
        are only fully closed when :meth:`close` is called.  This method
        only removes the server from the registry's lookup tables.

        Returns:
            ``True`` if the server was registered, ``False`` otherwise.
        """
        if server_name not in self._sessions:
            return False

        del self._sessions[server_name]
        for name in self._server_tool_names.pop(server_name, []):
            self._tools.pop(name, None)
            self._adapters.pop(name, None)
        self._configs.pop(server_name, None)
        logger.info("Unregistered server '%s'", server_name)
        return True

    # ------------------------------------------------------------------
    # Retrieval
    # ------------------------------------------------------------------

    def get_tool(self, namespaced_name: str) -> StructuredTool | None:
        """Return the tool registered as *namespaced_name*, or ``None``.

        Args:
            namespaced_name: Colon-namespaced name, e.g. ``"github:list_issues"``.
        """
        return self._tools.get(namespaced_name)

    def get_tools(
        self,
        *,
        server: str | None = None,
        category: str | None = None,
        pattern: str | None = None,
    ) -> list[StructuredTool]:
        """Return registered tools, optionally filtered.

        Filters are combined (AND semantics).

        Args:
            server: If given, return only tools from this server.
            category: If given, filter by inferred category.  Supported
                values: ``"read"``, ``"write"``, ``"other"``.
            pattern: If given, filter tool names using :mod:`fnmatch`
                glob syntax, e.g. ``"github:list_*"``.

        Returns:
            Filtered list of :class:`~langchain_core.tools.StructuredTool`.
        """
        items: list[tuple[str, StructuredTool]] = list(self._tools.items())

        if server is not None:
            prefix = f"{server}:"
            items = [(n, t) for n, t in items if n.startswith(prefix)]

        if category is not None:
            items = [(n, t) for n, t in items if _infer_category(n) == category]

        if pattern is not None:
            items = [(n, t) for n, t in items if fnmatch.fnmatch(n, pattern)]

        return [t for _, t in items]

    # ------------------------------------------------------------------
    # Introspection
    # ------------------------------------------------------------------

    def registered_servers(self) -> list[str]:
        """Return a list of all registered server names."""
        return list(self._sessions.keys())

    def list_servers(self) -> list[str]:
        """Return all registered server names (alias for :meth:`registered_servers`)."""
        return self.registered_servers()

    def list_categories(self) -> list[str]:
        """Return the distinct inferred categories present in the registry.

        Returns:
            Sorted list of category strings (e.g. ``["other", "read", "write"]``).
        """
        return sorted({_infer_category(name) for name in self._tools})

    def registered_tools(self) -> list[str]:
        """Return all registered colon-namespaced tool names."""
        return list(self._tools.keys())

    def tools_for_server(self, server_name: str) -> list[str]:
        """Return colon-namespaced names for all tools from *server_name*.

        Returns an empty list if the server is not registered.
        """
        return list(self._server_tool_names.get(server_name, []))

    # ------------------------------------------------------------------
    # Usage statistics
    # ------------------------------------------------------------------

    def get_usage_stats(self) -> dict[str, dict[str, Any]]:
        """Return usage statistics for all tools with registered adapters.

        Tools registered manually via :meth:`register_tool` are excluded
        (no adapter to track calls).

        Returns:
            Mapping of namespaced tool name → metrics dict.  Each metrics
            dict contains ``name``, ``server_name``, ``mcp_tool_name``,
            ``call_count``, ``avg_latency_ms``, ``total_latency_ms``.
        """
        return {name: adapter.metrics() for name, adapter in self._adapters.items()}

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def close(self) -> None:
        """Close all subprocess connections managed by this registry.

        Calls :meth:`contextlib.AsyncExitStack.aclose` which tears down
        every :class:`~mcp.client.session.ClientSession` and subprocess
        established via :meth:`connect_server`.

        Sessions registered directly with :meth:`register_server` are
        **not** closed here — their lifecycle is managed by the caller.
        """
        await self._exit_stack.aclose()
        logger.info("Closed all managed server connections")

    # ------------------------------------------------------------------
    # Dunder helpers
    # ------------------------------------------------------------------

    def __len__(self) -> int:
        return len(self._tools)

    def __contains__(self, namespaced_name: str) -> bool:
        return namespaced_name in self._tools
