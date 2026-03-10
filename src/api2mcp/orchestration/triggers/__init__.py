# SPDX-License-Identifier: MIT
"""Orchestration triggers — webhook and schedule-based workflow launchers."""
from __future__ import annotations

from api2mcp.orchestration.triggers.config import (
    ScheduleTriggerConfig,
    WebhookTriggerConfig,
)
from api2mcp.orchestration.triggers.scheduler import ScheduleTrigger
from api2mcp.orchestration.triggers.webhook import WebhookTrigger

__all__ = [
    "WebhookTrigger",
    "ScheduleTrigger",
    "WebhookTriggerConfig",
    "ScheduleTriggerConfig",
]
