# SPDX-License-Identifier: MIT
"""Validation-specific exceptions."""

from __future__ import annotations

from api2mcp.core.exceptions import API2MCPError


class ValidationError(API2MCPError):
    """Raised when tool input fails validation."""

    def __init__(self, message: str, field: str = "", code: str = "invalid") -> None:
        self.field = field
        self.code = code
        super().__init__(message)


class SizeExceededError(ValidationError):
    """Raised when input exceeds configured size limits."""

    def __init__(self, field: str, actual: int, limit: int) -> None:
        self.actual = actual
        self.limit = limit
        super().__init__(
            f"Field '{field}' size {actual} exceeds limit {limit}.",
            field=field,
            code="size_exceeded",
        )


class InjectionDetectedError(ValidationError):
    """Raised when an injection attack pattern is detected."""

    def __init__(self, field: str, attack_type: str) -> None:
        self.attack_type = attack_type
        super().__init__(
            f"Potential {attack_type} detected in field '{field}'.",
            field=field,
            code=f"injection_{attack_type.lower().replace(' ', '_')}",
        )


class SchemaValidationError(ValidationError):
    """Raised when input fails JSON Schema validation."""

    def __init__(self, message: str, field: str = "") -> None:
        super().__init__(message, field=field, code="schema_invalid")


class ContentTypeError(ValidationError):
    """Raised when an argument value has an unexpected content type."""

    def __init__(self, field: str, expected: str, actual: str) -> None:
        super().__init__(
            f"Field '{field}' expected {expected}, got {actual}.",
            field=field,
            code="content_type_invalid",
        )
