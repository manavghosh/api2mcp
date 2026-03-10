# SPDX-License-Identifier: MIT
"""Injection attack detection and string sanitization.

Detects the following attack categories in string field values:
- Path traversal  (``../``, ``..\\``, absolute Unix/Windows paths)
- Command injection  (shell metacharacters: ``;``, ``|``, ``&``, backtick, ``$(``
- SQL injection  (``' OR``, ``UNION SELECT``, comment sequences ``--``, ``/*``)
- XSS  (``<script>``, ``javascript:``, ``on*=`` event attributes)

Each category is independently configurable.  Detection raises
:class:`~api2mcp.validation.exceptions.InjectionDetectedError`; no input is
silently mutated by default.

A separate :func:`sanitize_html` function escapes HTML entities for string
fields that will be embedded in HTML contexts.
"""

from __future__ import annotations

import html
import re
from dataclasses import dataclass
from typing import Any

from api2mcp.validation.exceptions import InjectionDetectedError

# ---------------------------------------------------------------------------
# Compiled patterns
# ---------------------------------------------------------------------------

_PATH_TRAVERSAL_RE = re.compile(
    r"(\.\.[/\\])|"          # ../  ..\
    r"(^[/\\])|"             # Leading / or \
    r"(%2e%2e[%2f%5c])",     # URL-encoded ../
    re.IGNORECASE,
)

_COMMAND_INJECTION_RE = re.compile(
    r"[;|`]|"                # Shell separators/pipe/backtick
    r"\$\(|"                 # $(cmd)
    r"\$\{|"                 # ${var}
    r"&&|\|\||"              # && and ||
    r">\s*/dev/|"            # Redirect to /dev/*
    r"\bnc\s+-[el]",         # netcat reverse shell flags
    re.IGNORECASE,
)

_SQL_INJECTION_RE = re.compile(
    r"(\b(union|select|insert|update|delete|drop|create|alter|exec|execute)\b.*\b(from|into|table|where)\b)|"
    r"(--|/\*|\*/|;--)|"     # SQL comment sequences
    r"('\s*(or|and)\s*')|"   # ' OR ' / ' AND '
    r"('\s*(or|and)\s+\d)",  # ' OR 1
    re.IGNORECASE,
)

_XSS_RE = re.compile(
    r"<\s*script|"                      # <script
    r"javascript\s*:|"                   # javascript:
    r"vbscript\s*:|"                     # vbscript:
    r"on\w+\s*=|"                        # onerror=, onclick=, etc.
    r"<\s*iframe|"                       # <iframe
    r"<\s*img[^>]+src\s*=\s*[\"']?\s*javascript",  # <img src=javascript:
    re.IGNORECASE,
)


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

@dataclass
class SanitizerConfig:
    """Control which attack detectors are active.

    All detectors are enabled by default.  Disable selectively when a field
    legitimately contains patterns that would otherwise be flagged.
    """

    check_path_traversal: bool = True
    check_command_injection: bool = True
    check_sql_injection: bool = True
    check_xss: bool = True
    sanitize_html: bool = False  # Escape HTML entities (off by default)


_DEFAULT_CONFIG = SanitizerConfig()


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def check_string(
    value: str,
    field: str,
    config: SanitizerConfig = _DEFAULT_CONFIG,
) -> str:
    """Check *value* for attack patterns and optionally HTML-escape it.

    Returns the (possibly escaped) string.
    Raises :class:`~api2mcp.validation.exceptions.InjectionDetectedError`
    on any match.
    """
    if config.check_path_traversal and _PATH_TRAVERSAL_RE.search(value):
        raise InjectionDetectedError(field=field, attack_type="path traversal")

    if config.check_sql_injection and _SQL_INJECTION_RE.search(value):
        raise InjectionDetectedError(field=field, attack_type="SQL injection")

    if config.check_command_injection and _COMMAND_INJECTION_RE.search(value):
        raise InjectionDetectedError(field=field, attack_type="command injection")

    if config.check_xss and _XSS_RE.search(value):
        raise InjectionDetectedError(field=field, attack_type="XSS")

    if config.sanitize_html:
        return html.escape(value, quote=True)
    return value


def sanitize_arguments(
    arguments: dict[str, Any],
    config: SanitizerConfig = _DEFAULT_CONFIG,
) -> dict[str, Any]:
    """Recursively sanitize all string values in *arguments*.

    Returns a new dict with sanitized values (original is not mutated).
    """
    return {k: _sanitize_value(v, path=k, config=config) for k, v in arguments.items()}


def _sanitize_value(value: Any, path: str, config: SanitizerConfig) -> Any:
    if isinstance(value, str):
        return check_string(value, field=path, config=config)
    if isinstance(value, list):
        return [_sanitize_value(item, f"{path}[{i}]", config) for i, item in enumerate(value)]
    if isinstance(value, dict):
        return {k: _sanitize_value(v, f"{path}.{k}", config) for k, v in value.items()}
    return value


def sanitize_html(value: str) -> str:
    """HTML-escape *value* (convenience wrapper)."""
    return html.escape(value, quote=True)
