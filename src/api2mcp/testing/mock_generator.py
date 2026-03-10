# SPDX-License-Identifier: MIT
"""Mock API response generator — F6.3 Testing Framework.

Generates mock HTTP responses from OpenAPI spec examples and schemas,
supporting success, error, and edge-case scenarios.
"""

from __future__ import annotations

import random
import string
from typing import Any

from api2mcp.core.ir_schema import APISpec, Endpoint, ParameterLocation

# ---------------------------------------------------------------------------
# Scenario types
# ---------------------------------------------------------------------------


class MockScenario:
    """Defines how to generate a mock response.

    Attributes:
        name:        Human-readable scenario name.
        status_code: HTTP status code to return.
        body:        Response body dict (or None for empty body).
        headers:     Extra response headers.
    """

    def __init__(
        self,
        name: str,
        status_code: int = 200,
        body: dict[str, Any] | list[Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        self.name = name
        self.status_code = status_code
        self.body = body
        self.headers = headers or {}

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "status_code": self.status_code,
            "body": self.body,
            "headers": self.headers,
        }


# ---------------------------------------------------------------------------
# Mock generator
# ---------------------------------------------------------------------------


class MockResponseGenerator:
    """Generate mock responses from an :class:`~api2mcp.core.ir_schema.APISpec`.

    Given an API spec, this class produces per-endpoint mock scenarios that
    can be used by :class:`~api2mcp.testing.client.MCPTestClient` to simulate
    API responses without making real HTTP calls.

    Args:
        api_spec: The parsed API specification.
        seed:     Optional random seed for deterministic generation.

    Usage::

        generator = MockResponseGenerator(api_spec)
        scenarios = generator.scenarios_for("list_issues")
        # → [MockScenario("success", 200, ...), MockScenario("not_found", 404, ...)]
    """

    def __init__(self, api_spec: APISpec, *, seed: int | None = None) -> None:
        self.api_spec = api_spec
        self._rng = random.Random(seed)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def scenarios_for(self, tool_name: str) -> list[MockScenario]:
        """Return mock scenarios for the endpoint matching *tool_name*.

        Args:
            tool_name: The MCP tool name (e.g. ``"list_issues"``).

        Returns:
            List of :class:`MockScenario` objects (success + error cases).

        Raises:
            KeyError: If no endpoint matches *tool_name*.
        """
        endpoint = self._find_endpoint(tool_name)
        if endpoint is None:
            raise KeyError(f"No endpoint found for tool name: {tool_name!r}")
        return self._generate_scenarios(endpoint)

    def all_scenarios(self) -> dict[str, list[MockScenario]]:
        """Return scenarios for every endpoint in the spec.

        Returns:
            Mapping of tool name → list of :class:`MockScenario`.
        """
        result: dict[str, list[MockScenario]] = {}
        for endpoint in self.api_spec.endpoints:
            tool_name = self._endpoint_to_tool_name(endpoint)
            result[tool_name] = self._generate_scenarios(endpoint)
        return result

    def success_body(self, tool_name: str) -> dict[str, Any] | list[Any]:
        """Return just the success scenario body for *tool_name*.

        Args:
            tool_name: MCP tool name.

        Returns:
            Mock response body.
        """
        scenarios = self.scenarios_for(tool_name)
        success = next((s for s in scenarios if s.status_code == 200), scenarios[0])
        return success.body or {}

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _find_endpoint(self, tool_name: str) -> Endpoint | None:
        for endpoint in self.api_spec.endpoints:
            if self._endpoint_to_tool_name(endpoint) == tool_name:
                return endpoint
        return None

    @staticmethod
    def _endpoint_to_tool_name(endpoint: Endpoint) -> str:
        """Derive a tool name from an endpoint — mirrors ToolGenerator logic."""
        method = endpoint.method.value.lower()
        path_parts = [p.strip("/").replace("{", "").replace("}", "") for p in endpoint.path.split("/") if p]
        name = "_".join([method] + path_parts)
        return name[:64]

    def _generate_scenarios(self, endpoint: Endpoint) -> list[MockScenario]:
        scenarios: list[MockScenario] = []

        # Success scenario
        scenarios.append(
            MockScenario(
                name="success",
                status_code=200,
                body=self._generate_body(endpoint),
            )
        )

        # 404 for GET endpoints with path parameters
        has_path_param = any(
            p.location == ParameterLocation.PATH
            for p in endpoint.parameters
        )
        if endpoint.method.value.upper() == "GET" and has_path_param:
            scenarios.append(
                MockScenario(
                    name="not_found",
                    status_code=404,
                    body={"error": "not_found", "message": "Resource not found"},
                )
            )

        # 401 for any authenticated endpoint
        scenarios.append(
            MockScenario(
                name="unauthorized",
                status_code=401,
                body={"error": "unauthorized", "message": "Authentication required"},
            )
        )

        # 422 / 400 for mutation endpoints
        if endpoint.method.value.upper() in ("POST", "PUT", "PATCH"):
            scenarios.append(
                MockScenario(
                    name="validation_error",
                    status_code=422,
                    body={
                        "error": "validation_error",
                        "detail": [{"field": "body", "msg": "Field required"}],
                    },
                )
            )

        return scenarios

    def _generate_body(self, endpoint: Endpoint) -> dict[str, Any] | list[Any]:
        """Generate a plausible mock response body."""
        # List endpoints return arrays
        if endpoint.method.value.upper() == "GET" and not any(
            p.location == ParameterLocation.PATH for p in endpoint.parameters
        ):
            return [self._generate_item(), self._generate_item()]
        return self._generate_item()

    def _generate_item(self) -> dict[str, Any]:
        return {
            "id": self._rng.randint(1, 9999),
            "name": "".join(self._rng.choices(string.ascii_lowercase, k=8)),
            "created_at": "2025-01-01T00:00:00Z",
            "status": self._rng.choice(["active", "inactive", "pending"]),
        }
