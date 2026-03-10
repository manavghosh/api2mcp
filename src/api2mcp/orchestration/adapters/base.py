# SPDX-License-Identifier: MIT
"""MCP Tool Adapter — bridges MCP tools to LangChain's StructuredTool interface.

Uses the ``StructuredTool.from_function()`` factory pattern (not a BaseTool
subclass) for resilience to langchain-core API changes.

Usage::

    async with ClientSession(read, write) as session:
        await session.initialize()
        tools = await session.list_tools()

        structured_tool = await MCPToolAdapter.from_mcp_tool(
            session, tools.tools[0], "github"
        )
        result = await structured_tool.ainvoke({"owner": "user", "repo": "project"})
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable
from typing import Any

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field, create_model
from tenacity import (
    AsyncRetrying,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# JSON Schema → Python type mapping
# ---------------------------------------------------------------------------

_JSON_TYPE_MAP: dict[str, type] = {
    "string": str,
    "integer": int,
    "number": float,
    "boolean": bool,
    "array": list,
    "object": dict,
}


def _json_schema_to_pydantic(tool_name: str, schema: dict[str, Any]) -> type[BaseModel]:
    """Convert an MCP tool's JSON Schema ``inputSchema`` into a Pydantic model.

    Mapping:
    - ``string``  → ``str``
    - ``integer`` → ``int``
    - ``number``  → ``float``
    - ``boolean`` → ``bool``
    - ``array``   → ``list``
    - ``object``  → ``dict``

    Required fields are mapped to ``...`` (no default); optional fields
    default to ``None``.

    Args:
        tool_name: Used to build a unique model class name.
        schema: JSON Schema dict (typically ``tool.inputSchema``).

    Returns:
        A dynamically created :class:`pydantic.BaseModel` subclass.
    """
    properties: dict[str, Any] = schema.get("properties", {})
    required: set[str] = set(schema.get("required", []))

    fields: dict[str, Any] = {}
    for prop_name, prop_schema in properties.items():
        json_type = prop_schema.get("type", "string")
        python_type: type = _JSON_TYPE_MAP.get(json_type, str)
        description: str = prop_schema.get("description", "")

        if prop_name in required:
            fields[prop_name] = (python_type, Field(..., description=description))
        else:
            fields[prop_name] = (
                python_type | None,
                Field(default=None, description=description),
            )

    model_name = f"{tool_name}Args"
    if not fields:
        return create_model(model_name)
    return create_model(model_name, **fields)


# ---------------------------------------------------------------------------
# Result extraction
# ---------------------------------------------------------------------------


def _extract_text(content: list[Any]) -> str:
    """Extract text from ``CallToolResult.content``.

    Handles :class:`~mcp.types.TextContent`, :class:`~mcp.types.ImageContent`,
    and :class:`~mcp.types.EmbeddedResource` by extracting their text/data.
    """
    parts: list[str] = []
    for item in content:
        if hasattr(item, "text") and item.text is not None:
            parts.append(item.text)
        elif hasattr(item, "data") and item.data is not None:
            parts.append(str(item.data))
        else:
            parts.append(str(item))
    return "\n".join(parts) if parts else ""


# ---------------------------------------------------------------------------
# Adapter
# ---------------------------------------------------------------------------


class MCPToolAdapter:
    """Adapts an MCP tool to LangChain's StructuredTool interface.

    **Do not instantiate directly** — use :meth:`from_mcp_tool` instead.

    The adapter tracks per-tool latency metrics and wraps execution with
    configurable retry (tenacity exponential backoff) and timeout.

    Attributes:
        name: Colon-namespaced tool name, e.g. ``"github:list_issues"``.
        description: Human-readable tool description forwarded to the LLM.
        server_name: MCP server identifier.
        timeout_seconds: Per-call asyncio timeout.
        retry_count: Maximum tenacity retry attempts.
    """

    def __init__(
        self,
        *,
        session: Any,  # mcp.client.session.ClientSession
        mcp_tool_name: str,
        server_name: str,
        name: str,
        description: str,
        args_schema: type[BaseModel],
        timeout_seconds: float = 30.0,
        retry_count: int = 3,
        response_transformer: Callable[[str], str] | None = None,
    ) -> None:
        self._session = session
        self._mcp_tool_name = mcp_tool_name
        self.server_name = server_name
        self.name = name
        self.description = description
        self.args_schema = args_schema
        self.timeout_seconds = timeout_seconds
        self.retry_count = retry_count
        self._response_transformer = response_transformer
        self._call_count: int = 0
        self._total_latency_ms: float = 0.0

    # ------------------------------------------------------------------
    # Factory (returns StructuredTool)
    # ------------------------------------------------------------------

    @classmethod
    async def from_mcp_tool(
        cls,
        session: Any,
        tool: Any,  # mcp.types.Tool
        server_name: str,
        *,
        timeout_seconds: float = 30.0,
        retry_count: int = 3,
        response_transformer: Callable[[str], str] | None = None,
    ) -> StructuredTool:
        """Convert an MCP :class:`~mcp.types.Tool` into a LangChain StructuredTool.

        Args:
            session: Active :class:`~mcp.client.session.ClientSession`.
            tool: The :class:`~mcp.types.Tool` definition from ``list_tools()``.
            server_name: Identifier for the MCP server (used in namespacing).
            timeout_seconds: Per-call asyncio timeout in seconds.
            retry_count: Maximum retry attempts on transient errors.
            response_transformer: Optional callable applied to the raw result
                string before returning to the LLM.

        Returns:
            A :class:`~langchain_core.tools.StructuredTool` ready for use in
            LangGraph agents.

        Example::

            tool = await MCPToolAdapter.from_mcp_tool(session, mcp_tool, "github")
            result = await tool.ainvoke({"owner": "user", "repo": "project"})
        """
        schema: dict[str, Any] = tool.inputSchema if tool.inputSchema else {}
        args_schema = _json_schema_to_pydantic(tool.name, schema)

        namespaced_name = f"{server_name}:{tool.name}"
        description = (
            tool.description
            or f"MCP tool '{tool.name}' from server '{server_name}'"
        )

        adapter = cls(
            session=session,
            mcp_tool_name=tool.name,
            server_name=server_name,
            name=namespaced_name,
            description=description,
            args_schema=args_schema,
            timeout_seconds=timeout_seconds,
            retry_count=retry_count,
            response_transformer=response_transformer,
        )
        return adapter.to_structured_tool()

    # ------------------------------------------------------------------
    # Execution
    # ------------------------------------------------------------------

    async def _execute(self, **kwargs: Any) -> str:
        """Execute the MCP tool call with retry and timeout.

        Retries on :class:`asyncio.TimeoutError` and :class:`ConnectionError`
        using exponential backoff (tenacity).

        Args:
            **kwargs: Arguments matching :attr:`args_schema` fields.

        Returns:
            Text content extracted from the MCP ``CallToolResult``.

        Raises:
            RuntimeError: If the tool returns an error payload or all retries
                are exhausted.
            asyncio.TimeoutError: If the call exceeds :attr:`timeout_seconds`
                on the final attempt.
        """
        arguments = {k: v for k, v in kwargs.items() if v is not None} or None

        async for attempt in AsyncRetrying(
            stop=stop_after_attempt(self.retry_count),
            wait=wait_exponential(multiplier=1, min=1, max=10),
            retry=retry_if_exception_type(
                (asyncio.TimeoutError, ConnectionError, OSError)
            ),
            reraise=True,
        ):
            with attempt:
                t_start = time.monotonic()
                try:
                    result = await asyncio.wait_for(
                        self._session.call_tool(
                            name=self._mcp_tool_name,
                            arguments=arguments,
                        ),
                        timeout=self.timeout_seconds,
                    )
                except TimeoutError:
                    elapsed_ms = (time.monotonic() - t_start) * 1000
                    logger.warning(
                        "Tool '%s' timed out after %.0fms (limit=%.1fs)",
                        self.name,
                        elapsed_ms,
                        self.timeout_seconds,
                    )
                    raise
                finally:
                    elapsed_ms = (time.monotonic() - t_start) * 1000
                    self._call_count += 1
                    self._total_latency_ms += elapsed_ms

                if getattr(result, "isError", False):
                    error_text = _extract_text(result.content)
                    logger.error(
                        "Tool '%s' returned MCP error: %s", self.name, error_text
                    )
                    raise RuntimeError(
                        f"MCP tool '{self._mcp_tool_name}' error: {error_text}"
                    )

                raw = _extract_text(result.content)
                return (
                    self._response_transformer(raw)
                    if self._response_transformer
                    else raw
                )

        # Unreachable — tenacity reraises; silences mypy
        raise RuntimeError(
            f"Tool '{self.name}' failed after {self.retry_count} attempts"
        )

    # ------------------------------------------------------------------
    # StructuredTool factory
    # ------------------------------------------------------------------

    def to_structured_tool(self) -> StructuredTool:
        """Return a :class:`~langchain_core.tools.StructuredTool` wrapping this adapter.

        The returned tool uses the bound :meth:`_execute` coroutine and the
        dynamically generated Pydantic :attr:`args_schema`.
        """
        return StructuredTool.from_function(
            coroutine=self._execute,
            name=self.name,
            description=self.description,
            args_schema=self.args_schema,
        )

    # ------------------------------------------------------------------
    # Metrics
    # ------------------------------------------------------------------

    @property
    def call_count(self) -> int:
        """Total number of calls attempted through this adapter."""
        return self._call_count

    @property
    def avg_latency_ms(self) -> float:
        """Average call latency in milliseconds (0.0 if no calls made)."""
        if self._call_count == 0:
            return 0.0
        return self._total_latency_ms / self._call_count

    def metrics(self) -> dict[str, Any]:
        """Return a snapshot of call metrics for this adapter.

        Returns:
            Dict with ``name``, ``server_name``, ``mcp_tool_name``,
            ``call_count``, ``avg_latency_ms``, ``total_latency_ms``.
        """
        return {
            "name": self.name,
            "server_name": self.server_name,
            "mcp_tool_name": self._mcp_tool_name,
            "call_count": self._call_count,
            "avg_latency_ms": round(self.avg_latency_ms, 2),
            "total_latency_ms": round(self._total_latency_ms, 2),
        }
