# SPDX-License-Identifier: MIT
"""Input validation and sanitization for API2MCP tool calls."""

from api2mcp.validation.exceptions import (
    ContentTypeError,
    InjectionDetectedError,
    SchemaValidationError,
    SizeExceededError,
    ValidationError,
)
from api2mcp.validation.limits import SizeLimits, check_field_sizes, check_payload_size
from api2mcp.validation.pipeline import ValidationConfig, ValidationMiddleware, validate_tool_input
from api2mcp.validation.sanitizer import SanitizerConfig, sanitize_arguments, sanitize_html
from api2mcp.validation.schema import (
    check_required_fields,
    infer_string_fields,
    validate_against_schema,
)

__all__ = [
    # Exceptions
    "ContentTypeError",
    "InjectionDetectedError",
    "SchemaValidationError",
    "SizeExceededError",
    "ValidationError",
    # Limits
    "SizeLimits",
    "check_field_sizes",
    "check_payload_size",
    # Pipeline
    "ValidationConfig",
    "ValidationMiddleware",
    "validate_tool_input",
    # Sanitizer
    "SanitizerConfig",
    "sanitize_arguments",
    "sanitize_html",
    # Schema
    "check_required_fields",
    "infer_string_fields",
    "validate_against_schema",
]
