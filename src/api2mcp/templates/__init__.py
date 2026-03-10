# SPDX-License-Identifier: MIT
"""Template registry and installer for F7.1."""

from api2mcp.templates.installer import InstalledTemplate, TemplateInstaller
from api2mcp.templates.manifest import ReviewEntry, TemplateManifest, VersionEntry
from api2mcp.templates.registry import RegistryIndex, TemplateRegistry

__all__ = [
    "TemplateManifest",
    "VersionEntry",
    "ReviewEntry",
    "RegistryIndex",
    "TemplateRegistry",
    "TemplateInstaller",
    "InstalledTemplate",
]
