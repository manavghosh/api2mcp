# SPDX-License-Identifier: MIT
"""Full input validation pipeline.

Orchestrates the four validation stages in order:

1. **Payload size check** — reject oversized inputs before any parsing
2. **Schema validation** — type and required-field checks via JSON Schema
3. **Injection detection** — security pattern matching on string fields
4. **Field size check** — per-field string / array / object limits

The pipeline produces a :class:`ValidationResult` and either returns
sanitized arguments or raises a :class:`~api2mcp.validation.exceptions.ValidationError`.

Integrates as a :class:`ValidationMiddleware` that wraps the tool call handler.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from mcp.types import TextContent

from api2mcp.validation.exceptions import ValidationError
from api2mcp.validation.limits import SizeLimits, check_field_sizes, check_payload_size
from api2mcp.validation.sanitizer import SanitizerConfig, sanitize_arguments
from api2mcp.validation.schema import check_required_fields, validate_against_schema

logger = logging.getLogger(__name__)

ToolHandler = Callable[[str, dict[str, Any] | None], Awaitable[list[TextContent]]]


@dataclass
class ValidationConfig:
    """Master configuration for the validation pipeline.

    Args:
        enabled: Master switch — set False to bypass all validation.
        size_limits: Size enforcement config.
        sanitizer: Injection detection config.
        raise_on_error: If True raise; if False return an error TextContent.
    """

    enabled: bool = True
    size_limits: SizeLimits = field(default_factory=SizeLimits)
    sanitizer: SanitizerConfig = field(default_factory=SanitizerConfig)
    raise_on_error: bool = False  # MCP servers should return errors, not raise


def validate_tool_input(
    tool_name: str,
    arguments: dict[str, Any] | None,
    schema: dict[str, Any],
    *,
    config: ValidationConfig | None = None,
) -> dict[str, Any]:
    """Run the full validation pipeline and return sanitized arguments.

    Args:
        tool_name: Used in error messages.
        arguments: Raw tool call arguments (may be None → treated as empty).
        schema: JSON Schema from the tool definition.
        config: Validation configuration.

    Returns:
        Sanitized (and schema-validated) arguments dict.

    Raises:
        :class:`~api2mcp.validation.exceptions.ValidationError`:
            On any validation failure.
    """
    cfg = config or ValidationConfig()
    args = arguments or {}

    if not cfg.enabled:
        return args

    # Stage 1: payload size
    check_payload_size(args, cfg.size_limits)

    # Stage 2: schema validation (required fields + types)
    check_required_fields(args, schema, tool_name=tool_name)
    validate_against_schema(args, schema, tool_name=tool_name)

    # Stage 3: injection detection + optional HTML sanitization
    sanitized = sanitize_arguments(args, cfg.sanitizer)

    # Stage 4: per-field size limits
    check_field_sizes(sanitized, cfg.size_limits)

    return sanitized


class ValidationMiddleware:
    """Middleware that runs the validation pipeline before every tool call.

    Wraps a :class:`ToolHandler` and stores the tool schemas so it can
    validate each call against the correct schema.

    Usage::

        schemas = {tool.name: tool.input_schema for tool in tools}
        middleware = ValidationMiddleware(schemas)
        wrapped = middleware.wrap(raw_handler)
    """

    def __init__(
        self,
        schemas: dict[str, dict[str, Any]],
        *,
        config: ValidationConfig | None = None,
    ) -> None:
        self._schemas = schemas
        self._config = config or ValidationConfig()

    def wrap(self, handler: ToolHandler) -> ToolHandler:
        """Return a new handler that validates input before calling *handler*."""
        cfg = self._config
        schemas = self._schemas

        async def validated_handler(
            name: str, arguments: dict[str, Any] | None
        ) -> list[TextContent]:
            schema = schemas.get(name, {"type": "object"})
            try:
                sanitized = validate_tool_input(
                    name, arguments, schema, config=cfg
                )
            except ValidationError as exc:
                logger.warning("Validation failed for tool '%s': %s", name, exc)
                if cfg.raise_on_error:
                    raise
                return [
                    TextContent(
                        type="text",
                        text=json.dumps({"error": str(exc), "code": exc.code}),
                    )
                ]
            return await handler(name, sanitized)

        return validated_handler
