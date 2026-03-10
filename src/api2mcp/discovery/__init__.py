# SPDX-License-Identifier: MIT
"""API Spec Auto-Discovery (F3.4)."""

from .discoverer import (
    DiscoveredSpec,
    DiscoveryResult,
    SpecDiscoverer,
    SpecFormat,
    detect_format_from_content,
    detect_format_from_url,
)

__all__ = [
    "DiscoveredSpec",
    "DiscoveryResult",
    "SpecDiscoverer",
    "SpecFormat",
    "detect_format_from_content",
    "detect_format_from_url",
]
