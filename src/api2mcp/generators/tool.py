# SPDX-License-Identifier: MIT
"""MCP Tool Generator — IR to MCP tool definitions (TASK-016, TASK-017).

Consumes IR (APISpec) and produces MCP-compliant tool definitions.
Supports:
- JSON Schema input_schema generation
- Jinja2 template-based server code generation
- Edge cases: no parameters, file uploads, multipart, empty responses
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import jinja2

from api2mcp.core.exceptions import GeneratorException
from api2mcp.core.ir_schema import APISpec, Endpoint, ParameterLocation
from api2mcp.generators.naming import (
    derive_tool_name,
    resolve_collisions,
    sanitize_name,
)
from api2mcp.generators.schema_mapper import build_input_schema

logger = logging.getLogger(__name__)

# Default template directory (package-relative)
_TEMPLATE_DIR = Path(__file__).parent.parent / "templates" / "tools"


@dataclass
class MCPToolDef:
    """A generated MCP tool definition.

    Represents a single tool in the MCP tools/list response.
    """

    name: str
    description: str
    input_schema: dict[str, Any]
    endpoint: Endpoint
    body_param_names: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    timeout: float | None = None

    def to_mcp_dict(self) -> dict[str, Any]:
        """Convert to the dict format expected by MCP protocol."""
        return {
            "name": self.name,
            "description": self.description,
            "inputSchema": self.input_schema,
        }


class ToolGenerator:
    """Generates MCP tool definitions and server code from IR.

    Args:
        max_depth: Maximum nesting depth for schema simplification.
        template_dir: Override the Jinja2 template directory.
    """

    def __init__(
        self,
        max_depth: int = 5,
        template_dir: Path | None = None,
    ) -> None:
        self.max_depth = max_depth
        self.template_dir = template_dir or _TEMPLATE_DIR
        self._jinja_env: jinja2.Environment | None = None

    @property
    def jinja_env(self) -> jinja2.Environment:
        """Lazily create Jinja2 environment."""
        if self._jinja_env is None:
            self._jinja_env = jinja2.Environment(
                loader=jinja2.FileSystemLoader(str(self.template_dir)),
                autoescape=False,
                trim_blocks=True,
                lstrip_blocks=True,
                keep_trailing_newline=True,
            )
        return self._jinja_env

    def generate(self, api_spec: APISpec) -> list[MCPToolDef]:
        """Generate MCP tool definitions from an IR APISpec.

        Args:
            api_spec: Parsed API specification (IR).

        Returns:
            List of MCPToolDef objects, one per endpoint.

        Raises:
            GeneratorException: If generation fails for any endpoint.
        """
        # Emit PRE_GENERATE hook
        try:
            from api2mcp.plugins import get_hook_manager
            from api2mcp.plugins.hooks import PRE_GENERATE
            get_hook_manager().emit_sync(PRE_GENERATE, api_spec=api_spec)
        except Exception:  # noqa: BLE001
            pass  # plugins are optional

        if not api_spec.endpoints:
            logger.warning("API spec '%s' has no endpoints — no tools generated", api_spec.title)
            return []

        # Resolve names with collision handling
        name_map = resolve_collisions(api_spec.endpoints)

        tools: list[MCPToolDef] = []
        for endpoint in api_spec.endpoints:
            try:
                tool = self._endpoint_to_tool(endpoint, name_map)
                tools.append(tool)
            except Exception as exc:
                raise GeneratorException(
                    f"Failed to generate tool for {endpoint.method.value} {endpoint.path}: {exc}",
                    endpoint=f"{endpoint.method.value} {endpoint.path}",
                ) from exc

        logger.info(
            "Generated %d tools from '%s' (v%s)",
            len(tools),
            api_spec.title,
            api_spec.version,
        )

        # Emit POST_GENERATE hook
        try:
            from api2mcp.plugins import get_hook_manager
            from api2mcp.plugins.hooks import POST_GENERATE
            get_hook_manager().emit_sync(POST_GENERATE, tools=tools)
        except Exception:  # noqa: BLE001
            pass  # plugins are optional

        return tools

    def generate_server_code(
        self,
        api_spec: APISpec,
        output_dir: Path,
        server_name: str | None = None,
    ) -> list[Path]:
        """Generate Python MCP server code from IR using Jinja2 templates.

        Args:
            api_spec: Parsed API specification.
            output_dir: Directory to write generated files.
            server_name: Override the server name (defaults to sanitized API title).

        Returns:
            List of generated file paths.
        """
        tools = self.generate(api_spec)
        if not tools:
            return []

        name = server_name or sanitize_name(api_spec.title)
        output_dir.mkdir(parents=True, exist_ok=True)

        generated: list[Path] = []

        # Generate server.py
        server_template = self.jinja_env.get_template("server.py.j2")
        server_code = server_template.render(
            api_spec=api_spec,
            tools=tools,
            server_name=name,
        )
        server_path = output_dir / "server.py"
        server_path.write_text(server_code, encoding="utf-8")
        generated.append(server_path)
        logger.info("Generated server code: %s", server_path)

        return generated

    def _endpoint_to_tool(
        self,
        endpoint: Endpoint,
        name_map: dict[str, str],
    ) -> MCPToolDef:
        """Convert a single IR endpoint to an MCPToolDef."""
        # Look up resolved name
        key = endpoint.operation_id or f"{endpoint.method.value} {endpoint.path}"
        name = name_map.get(key, derive_tool_name(endpoint))

        description = self._build_description(endpoint)
        input_schema = build_input_schema(endpoint, max_depth=self.max_depth)

        # Track body parameter names for template rendering
        body_param_names = self._extract_body_param_names(endpoint, input_schema)

        metadata: dict[str, Any] = {}
        if endpoint.tags:
            metadata["tags"] = endpoint.tags
        if endpoint.deprecated:
            metadata["deprecated"] = True

        return MCPToolDef(
            name=name,
            description=description,
            input_schema=input_schema,
            endpoint=endpoint,
            body_param_names=body_param_names,
            metadata=metadata,
        )

    def _build_description(self, endpoint: Endpoint) -> str:
        """Build a human-readable tool description from endpoint metadata."""
        parts: list[str] = []

        if endpoint.summary:
            parts.append(endpoint.summary)
        elif endpoint.description:
            # Use first sentence of description
            first_sentence = endpoint.description.split(".")[0].strip()
            if first_sentence:
                parts.append(first_sentence)
        else:
            # Fallback: generate from method + path
            parts.append(f"{endpoint.method.value} {endpoint.path}")

        if endpoint.deprecated:
            parts.append("[DEPRECATED]")

        return " ".join(parts)

    def _extract_body_param_names(
        self,
        endpoint: Endpoint,
        input_schema: dict[str, Any],
    ) -> list[str]:
        """Extract the parameter names that came from the request body.

        Used by templates to know which args to send as JSON body vs query/path params.
        """
        if endpoint.request_body is None:
            return []

        # Collect non-body parameter names
        non_body_params = {
            p.name
            for p in endpoint.parameters
            if p.location != ParameterLocation.BODY
        }

        # Body params = all input_schema properties minus non-body params
        all_props = set(input_schema.get("properties", {}).keys())
        body_props = all_props - non_body_params
        return sorted(body_props)
