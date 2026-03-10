# SPDX-License-Identifier: MIT
"""MCP Resource generator — converts GET API endpoints to MCP Resource definitions."""
from __future__ import annotations

import logging
from dataclasses import dataclass

from api2mcp.core.ir_schema import APISpec, HttpMethod

logger = logging.getLogger(__name__)


@dataclass
class MCPResourceDef:
    """Definition of an MCP Resource."""

    name: str
    uri_template: str
    description: str
    mime_type: str = "application/json"


class MCPResourceGenerator:
    """Converts GET endpoints from an APISpec into MCP Resource definitions.

    Only GET endpoints are converted (resources are read-only by convention).
    """

    def generate(self, api_spec: APISpec) -> list[MCPResourceDef]:
        """Generate resource definitions from *api_spec*.

        Args:
            api_spec: Parsed API specification.

        Returns:
            List of :class:`MCPResourceDef` for each GET endpoint.
        """
        resources: list[MCPResourceDef] = []
        base = (api_spec.base_url or "").rstrip("/")

        for endpoint in api_spec.endpoints:
            if endpoint.method != HttpMethod.GET:
                continue
            name = endpoint.operation_id or endpoint.path.strip("/").replace("/", "_")
            uri_template = f"{base}{endpoint.path}"
            description = endpoint.summary or f"Resource at {endpoint.path}"
            resources.append(
                MCPResourceDef(
                    name=name,
                    uri_template=uri_template,
                    description=description,
                )
            )
            logger.debug("Generated resource: %s → %s", name, uri_template)

        return resources
