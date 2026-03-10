# SPDX-License-Identifier: MIT
"""MCP Prompt generator — converts API endpoints to MCP Prompt definitions."""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from api2mcp.core.ir_schema import APISpec

logger = logging.getLogger(__name__)


@dataclass
class MCPPromptDef:
    """Definition of an MCP Prompt."""

    name: str
    description: str
    arguments: list[dict[str, Any]] = field(default_factory=list)
    template: str = ""


class MCPPromptGenerator:
    """Converts API endpoints into MCP Prompt definitions."""

    def generate(self, api_spec: APISpec) -> list[MCPPromptDef]:
        """Generate prompt definitions from *api_spec*.

        Args:
            api_spec: Parsed API specification.

        Returns:
            List of :class:`MCPPromptDef`, one per endpoint.
        """
        prompts: list[MCPPromptDef] = []

        for endpoint in api_spec.endpoints:
            name = endpoint.operation_id or endpoint.path.strip("/").replace("/", "_")
            description = endpoint.summary or f"Call {endpoint.method.value} {endpoint.path}"
            arguments = []
            for p in endpoint.parameters:
                arg: dict[str, Any] = {
                    "name": p.name,
                    "required": p.required,
                }
                # description field may be optional
                desc = getattr(p, "description", None) or p.name
                arg["description"] = desc
                arguments.append(arg)
            required_names = [p.name for p in endpoint.parameters if p.required]
            template = (
                f"Please call the '{name}' operation"
                + (f" with {', '.join(required_names)}" if required_names else "")
                + "."
            )
            prompts.append(
                MCPPromptDef(
                    name=name,
                    description=description,
                    arguments=arguments,
                    template=template,
                )
            )
            logger.debug("Generated prompt: %s", name)

        return prompts
