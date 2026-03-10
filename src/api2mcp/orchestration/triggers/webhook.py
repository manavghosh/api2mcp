# SPDX-License-Identifier: MIT
"""Webhook trigger — start a LangGraph workflow on HTTP POST."""
from __future__ import annotations

import hashlib
import hmac
import logging
import os
from collections.abc import Awaitable, Callable
from typing import Any

from api2mcp.orchestration.triggers.config import WebhookTriggerConfig

logger = logging.getLogger(__name__)


class WebhookTrigger:
    """HTTP webhook handler that starts an orchestration workflow on POST.

    Supports HMAC-SHA256 signature verification (GitHub-style webhooks).

    Args:
        config: Webhook trigger configuration.
        workflow_runner: Async callable that receives (prompt, payload) and runs
                         the workflow. If None, the webhook is accepted but no
                         workflow is started.
    """

    def __init__(
        self,
        config: WebhookTriggerConfig,
        workflow_runner: Callable[[str, dict[str, Any]], Awaitable[Any]] | None = None,
    ) -> None:
        self.config = config
        self._runner = workflow_runner

    def verify_signature(self, payload: bytes, signature: str) -> bool:
        """Verify HMAC-SHA256 signature for GitHub-style webhooks.

        Returns True if no secret is configured (open webhook).
        """
        if not self.config.secret_env:
            return True
        secret = os.environ.get(self.config.secret_env, "")
        if not secret:
            logger.warning(
                "WebhookTrigger %r: secret env var %r not set — rejecting",
                self.config.name,
                self.config.secret_env,
            )
            return False
        expected = "sha256=" + hmac.new(
            secret.encode(), payload, hashlib.sha256
        ).hexdigest()
        return hmac.compare_digest(expected, signature)

    async def handle(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Process a webhook payload and start the configured workflow."""
        prompt = self._render_prompt(payload)
        logger.info(
            "WebhookTrigger %r: starting %r workflow with prompt=%r",
            self.config.name,
            self.config.graph,
            prompt[:80],
        )
        if self._runner is not None:
            await self._runner(prompt, payload)
        return {"status": "accepted", "trigger": self.config.name}

    def _render_prompt(self, payload: dict[str, Any]) -> str:
        """Render the prompt template with payload values."""
        template = self.config.prompt_template
        if not template:
            return f"Webhook received: {self.config.name}"
        # Simple Jinja-like substitution for {{ payload.key }} patterns
        import re
        def _sub(match: re.Match) -> str:
            key = match.group(1).strip()
            return str(payload.get(key, match.group(0)))
        return re.sub(r"\{\{\s*payload\.(\w+)\s*\}\}", _sub, template)
