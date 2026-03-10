"""Tests for orchestration trigger system."""
from __future__ import annotations

import pytest


def test_triggers_module_importable():
    from api2mcp.orchestration import triggers
    assert triggers is not None


def test_webhook_trigger_config():
    from api2mcp.orchestration.triggers.config import WebhookTriggerConfig
    cfg = WebhookTriggerConfig(
        name="test-webhook",
        path="/webhooks/test",
        graph="reactive",
        servers=["github"],
        prompt_template="PR opened: {{ payload.title }}",
    )
    assert cfg.name == "test-webhook"
    assert cfg.type == "webhook"
    assert cfg.path == "/webhooks/test"


def test_schedule_trigger_config():
    from api2mcp.orchestration.triggers.config import ScheduleTriggerConfig
    cfg = ScheduleTriggerConfig(
        name="daily-sync",
        cron="0 9 * * *",
        graph="planner",
        servers=["github", "jira"],
        prompt="Sync all open GitHub issues to Jira",
    )
    assert cfg.name == "daily-sync"
    assert cfg.type == "schedule"
    assert cfg.cron == "0 9 * * *"


def test_webhook_trigger_no_secret_verifies_ok():
    from api2mcp.orchestration.triggers.config import WebhookTriggerConfig
    from api2mcp.orchestration.triggers.webhook import WebhookTrigger
    cfg = WebhookTriggerConfig(name="test", path="/hook", secret_env=None)
    trigger = WebhookTrigger(config=cfg)
    assert trigger.verify_signature(b"payload", "any_signature") is True


def test_webhook_trigger_bad_secret_rejects(monkeypatch):
    from api2mcp.orchestration.triggers.config import WebhookTriggerConfig
    from api2mcp.orchestration.triggers.webhook import WebhookTrigger
    monkeypatch.setenv("TEST_WEBHOOK_SECRET", "real_secret")
    cfg = WebhookTriggerConfig(name="test", path="/hook", secret_env="TEST_WEBHOOK_SECRET")
    trigger = WebhookTrigger(config=cfg)
    assert trigger.verify_signature(b"payload", "sha256=wrong") is False


@pytest.mark.asyncio
async def test_webhook_trigger_handle_calls_runner():
    from api2mcp.orchestration.triggers.config import WebhookTriggerConfig
    from api2mcp.orchestration.triggers.webhook import WebhookTrigger

    called_with = []

    async def mock_runner(prompt: str, payload: dict) -> None:
        called_with.append((prompt, payload))

    cfg = WebhookTriggerConfig(
        name="test",
        path="/hook",
        prompt_template="New event: {{ payload.action }}",
    )
    trigger = WebhookTrigger(config=cfg, workflow_runner=mock_runner)
    result = await trigger.handle({"action": "opened"})
    assert result["status"] == "accepted"
    assert len(called_with) == 1
    assert "opened" in called_with[0][0]


def test_schedule_trigger_stop():
    from api2mcp.orchestration.triggers.config import ScheduleTriggerConfig
    from api2mcp.orchestration.triggers.scheduler import ScheduleTrigger
    cfg = ScheduleTriggerConfig(name="test", cron="* * * * *", prompt="test prompt")
    trigger = ScheduleTrigger(config=cfg)
    trigger.stop()  # Should not raise
    assert trigger._running is False


def test_all_exports_present():
    from api2mcp.orchestration import triggers
    for name in ["WebhookTrigger", "ScheduleTrigger", "WebhookTriggerConfig", "ScheduleTriggerConfig"]:
        assert hasattr(triggers, name), f"triggers.{name} not exported"


# ---------------------------------------------------------------------------
# G26: Additional trigger tests
# ---------------------------------------------------------------------------


def test_webhook_trigger_instantiation_with_config():
    """WebhookTrigger can be instantiated with a config (no runner)."""
    from api2mcp.orchestration.triggers.config import WebhookTriggerConfig
    from api2mcp.orchestration.triggers.webhook import WebhookTrigger

    cfg = WebhookTriggerConfig(
        name="gh-webhook",
        path="/webhooks/github",
        graph="reactive",
        servers=["github"],
        prompt_template="Event: {{ payload.action }}",
    )
    trigger = WebhookTrigger(config=cfg)
    assert trigger.config is cfg
    assert trigger._runner is None


def test_next_sleep_seconds_wildcard_returns_0_to_60():
    """_next_sleep_seconds('* * * * *') must return a value in [0, 60]."""
    from api2mcp.orchestration.triggers.scheduler import _next_sleep_seconds

    secs = _next_sleep_seconds("* * * * *")
    assert 0 <= secs <= 60


def test_next_sleep_seconds_invalid_raises_value_error():
    """_next_sleep_seconds('invalid') must raise ValueError."""
    from api2mcp.orchestration.triggers.scheduler import _next_sleep_seconds

    with pytest.raises(ValueError):
        _next_sleep_seconds("invalid")


def test_next_sleep_seconds_wrong_field_count_raises_value_error():
    """_next_sleep_seconds with too few fields must raise ValueError."""
    from api2mcp.orchestration.triggers.scheduler import _next_sleep_seconds

    with pytest.raises(ValueError):
        _next_sleep_seconds("0 9 * *")  # only 4 fields


@pytest.mark.asyncio
async def test_schedule_trigger_fires_runner_when_loop_runs():
    """ScheduleTrigger invokes the workflow runner after the sleep elapses."""

    from api2mcp.orchestration.triggers.config import ScheduleTriggerConfig
    from api2mcp.orchestration.triggers.scheduler import ScheduleTrigger

    called_with: list[str] = []

    async def mock_runner(prompt: str) -> None:
        called_with.append(prompt)

    cfg = ScheduleTriggerConfig(
        name="test-sched",
        cron="* * * * *",
        prompt="Run scheduled workflow",
    )
    trigger = ScheduleTrigger(config=cfg, workflow_runner=mock_runner)

    # Patch asyncio.sleep to return immediately.
    # The loop structure is: sleep -> check _running -> fire runner -> loop back -> sleep again
    # We stop on the SECOND sleep call so the runner fires on the first iteration.
    sleep_count = 0

    async def fast_sleep(seconds: float) -> None:
        nonlocal sleep_count
        sleep_count += 1
        if sleep_count >= 2:
            trigger.stop()

    import unittest.mock as mock
    with mock.patch("api2mcp.orchestration.triggers.scheduler.asyncio.sleep", side_effect=fast_sleep):
        await trigger.start()

    assert len(called_with) == 1
    assert called_with[0] == "Run scheduled workflow"
