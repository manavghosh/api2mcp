# SPDX-License-Identifier: MIT
"""Configuration file loader for API2MCP CLI.

Supports `.api2mcp.yaml` configuration files with environment variable
interpolation (${VAR} syntax). CLI arguments always override config values.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

import yaml

_ENV_VAR_RE = re.compile(r"\$\{([^}]+)\}")

_CONFIG_FILENAMES = [".api2mcp.yaml", ".api2mcp.yml"]


def _interpolate_env_vars(value: Any) -> Any:
    """Recursively replace ${VAR} and ${VAR:-default} with environment variable values."""
    if isinstance(value, str):
        def _replace(match: re.Match[str]) -> str:
            expr = match.group(1)
            if ":-" in expr:
                var_name, default = expr.split(":-", 1)
                return os.environ.get(var_name.strip(), default)
            return os.environ.get(expr, match.group(0))
        return _ENV_VAR_RE.sub(_replace, value)
    if isinstance(value, dict):
        return {k: _interpolate_env_vars(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_interpolate_env_vars(item) for item in value]
    return value


def find_config_file(start: Path | None = None) -> Path | None:
    """Search for a config file starting from *start* (default: cwd) up to root."""
    directory = (start or Path.cwd()).resolve()
    for candidate in [directory, *directory.parents]:
        for name in _CONFIG_FILENAMES:
            path = candidate / name
            if path.is_file():
                return path
    return None


def load_config(config_path: Path | None = None) -> dict[str, Any]:
    """Load and return the configuration dictionary.

    If *config_path* is not given, auto-discovers the file. Returns an empty
    dict if no file is found.
    """
    path = config_path or find_config_file()
    if path is None:
        return {}
    if not path.is_file():
        return {}
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(raw, dict):
        return {}
    return _interpolate_env_vars(raw)  # type: ignore[return-value]


def merge_config(
    config: dict[str, Any],
    *,
    output: str | None = None,
    host: str | None = None,
    port: int | None = None,
    transport: str | None = None,
    log_level: str | None = None,
    auth: dict[str, Any] | None = None,
    secrets: dict[str, Any] | None = None,
    rate_limit: dict[str, Any] | None = None,
    validation: dict[str, Any] | None = None,
    cache: dict[str, Any] | None = None,
    pool: dict[str, Any] | None = None,
    circuit_breaker: dict[str, Any] | None = None,
    plugins: list[str] | None = None,
    tls_warning: bool | None = None,
    orchestration: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Merge CLI overrides on top of a loaded config dict.

    CLI arguments (non-None values) always take precedence.
    All config file sections (auth, secrets, etc.) pass through unchanged
    unless explicitly overridden.
    """
    merged: dict[str, Any] = dict(config)
    overrides: dict[str, Any] = {
        "output": output,
        "host": host,
        "port": port,
        "transport": transport,
        "log_level": log_level,
        "auth": auth,
        "secrets": secrets,
        "rate_limit": rate_limit,
        "validation": validation,
        "cache": cache,
        "pool": pool,
        "circuit_breaker": circuit_breaker,
        "plugins": plugins,
        "tls_warning": tls_warning,
        "orchestration": orchestration,
    }
    for key, val in overrides.items():
        if val is not None:
            merged[key] = val
    return merged
