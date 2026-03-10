# SPDX-License-Identifier: MIT
"""Custom exceptions for API2MCP parsing and validation."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class ParseError:
    """Structured parse/validation error with optional location info."""

    message: str
    line: int | None = None
    column: int | None = None
    path: str = ""
    severity: str = "error"  # "error" | "warning"

    def __str__(self) -> str:
        parts: list[str] = []
        if self.path:
            parts.append(f"at {self.path}")
        if self.line is not None:
            loc = f"line {self.line}"
            if self.column is not None:
                loc += f", col {self.column}"
            parts.append(loc)
        location = " ".join(parts)
        prefix = f"[{self.severity.upper()}]"
        suffix = f" ({location})" if location else ""
        return f"{prefix} {self.message}{suffix}"


class API2MCPError(Exception):
    """Base exception for all API2MCP errors."""

    code: str = "API2MCP_ERROR"


class ParseException(API2MCPError):
    """Raised when parsing an API specification fails."""

    code: str = "PARSE_ERROR"

    def __init__(self, message: str, errors: list[ParseError] | None = None) -> None:
        self.errors: list[ParseError] = errors or []
        super().__init__(message)

    def __str__(self) -> str:
        base = super().__str__()
        if self.errors:
            details = "\n".join(f"  - {e}" for e in self.errors)
            return f"{base}\n{details}"
        return base


class ValidationException(API2MCPError):
    """Raised when validation of a parsed spec fails."""

    code: str = "VALIDATION_ERROR"

    def __init__(self, message: str, errors: list[ParseError] | None = None) -> None:
        self.errors: list[ParseError] = errors or []
        super().__init__(message)

    def __str__(self) -> str:
        base = super().__str__()
        if self.errors:
            details = "\n".join(f"  - {e}" for e in self.errors)
            return f"{base}\n{details}"
        return base


class RefResolutionError(API2MCPError):
    """Raised when a $ref cannot be resolved."""

    code: str = "REF_RESOLUTION_ERROR"

    def __init__(self, ref: str, message: str = "") -> None:
        self.ref = ref
        super().__init__(message or f"Failed to resolve $ref: {ref}")


class CircularRefError(RefResolutionError):
    """Raised when a circular $ref chain is detected."""

    code: str = "CIRCULAR_REF_ERROR"

    def __init__(self, ref_chain: list[str]) -> None:
        self.ref_chain = ref_chain
        cycle = " -> ".join(ref_chain)
        super().__init__(ref_chain[-1], f"Circular $ref detected: {cycle}")


class GeneratorException(API2MCPError):
    """Raised when code generation fails."""

    code: str = "GENERATOR_ERROR"

    def __init__(self, message: str, endpoint: str = "") -> None:
        self.endpoint = endpoint
        super().__init__(message)


class RuntimeException(API2MCPError):
    """Raised when the MCP runtime server encounters an error."""

    code: str = "RUNTIME_ERROR"

    def __init__(self, message: str, transport: str = "") -> None:
        self.transport = transport
        super().__init__(message)


class TransportException(RuntimeException):
    """Raised when a transport-level error occurs."""

    code: str = "TRANSPORT_ERROR"


class ShutdownException(RuntimeException):
    """Raised when shutdown fails or times out."""

    code: str = "SHUTDOWN_ERROR"
