# SPDX-License-Identifier: MIT
"""Base parser interface for all API spec parsers."""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

from .exceptions import ParseError
from .ir_schema import APISpec


class BaseParser(ABC):
    """Abstract base class for all API specification parsers.

    Every parser (OpenAPI, GraphQL, Postman, Swagger) implements this
    interface and produces the same IR output (APISpec).
    """

    @abstractmethod
    async def parse(self, source: str | Path, **kwargs: Any) -> APISpec:
        """Parse an API specification and return an IR APISpec.

        Args:
            source: File path or URL to the API specification.
            **kwargs: Parser-specific options.

        Returns:
            Parsed APISpec intermediate representation.

        Raises:
            ParseException: If parsing fails due to invalid input.
            RefResolutionError: If $ref resolution fails.
        """
        ...

    @abstractmethod
    async def validate(self, source: str | Path, **kwargs: Any) -> list[ParseError]:
        """Validate an API specification without producing full IR.

        Returns:
            List of ParseError objects (empty list means valid).
        """
        ...

    @abstractmethod
    def detect(self, content: dict[str, Any]) -> bool:
        """Check if this parser can handle the given content.

        Args:
            content: Parsed YAML/JSON dict.

        Returns:
            True if this parser supports the format.
        """
        ...
