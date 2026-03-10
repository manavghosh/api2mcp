# SPDX-License-Identifier: MIT
"""Pydantic config models for orchestration triggers."""
from __future__ import annotations
from typing import Literal
from pydantic import BaseModel


class WebhookTriggerConfig(BaseModel):
    """Configuration for a webhook-based trigger."""
    name: str
    type: Literal["webhook"] = "webhook"
    path: str
    secret_env: str | None = None
    graph: str = "reactive"
    servers: list[str] = []
    prompt_template: str = ""


class ScheduleTriggerConfig(BaseModel):
    """Configuration for a schedule-based (cron) trigger."""
    name: str
    type: Literal["schedule"] = "schedule"
    cron: str
    graph: str = "reactive"
    servers: list[str] = []
    prompt: str = ""
