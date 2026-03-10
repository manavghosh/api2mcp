# SPDX-License-Identifier: MIT
"""Safe YAML/JSON loading with descriptive error messages."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml


def safe_yaml_load(text: str, source: str = "<string>") -> Any:
    """Parse YAML *text* and raise ValueError with context on failure."""
    try:
        return yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise ValueError(f"YAML parse error in {source}: {exc}") from exc


def safe_yaml_load_path(path: Path) -> Any:
    """Load and parse a YAML file, with descriptive error on failure."""
    return safe_yaml_load(path.read_text(encoding="utf-8"), source=str(path))


def safe_json_load(text: str, source: str = "<string>") -> Any:
    """Parse JSON *text* and raise ValueError with context on failure."""
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"JSON parse error in {source}: {exc}") from exc
