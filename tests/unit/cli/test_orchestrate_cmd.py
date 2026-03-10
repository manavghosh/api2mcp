"""Tests for api2mcp orchestrate CLI command."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from click.testing import CliRunner

from api2mcp.cli.commands.orchestrate import _run_workflow, orchestrate_cmd


# ---------------------------------------------------------------------------
# Existing smoke tests (preserved)
# ---------------------------------------------------------------------------

def test_orchestrate_help():
    runner = CliRunner()
    result = runner.invoke(orchestrate_cmd, ["--help"])
    assert result.exit_code == 0
    assert "--graph" in result.output
    assert "--server" in result.output
    assert "--model" in result.output
    assert "--stream" in result.output


def test_orchestrate_requires_prompt():
    runner = CliRunner()
    result = runner.invoke(orchestrate_cmd, [])
    assert result.exit_code != 0


def test_orchestrate_bad_server_format():
    """--server without '=' gives UsageError."""
    runner = CliRunner()
    result = runner.invoke(orchestrate_cmd, ["test prompt", "--server", "bad_no_equals"])
    assert result.exit_code != 0


def test_orchestrate_output_format_choices():
    runner = CliRunner()
    result = runner.invoke(orchestrate_cmd, ["--help"])
    assert "json" in result.output or "text" in result.output


# ---------------------------------------------------------------------------
# New --api-name option is surfaced in --help
# ---------------------------------------------------------------------------

def test_orchestrate_help_shows_api_name():
    runner = CliRunner()
    result = runner.invoke(orchestrate_cmd, ["--help"])
    assert result.exit_code == 0
    assert "--api-name" in result.output


# ---------------------------------------------------------------------------
# Helpers shared by _run_workflow tests
# ---------------------------------------------------------------------------

def _make_registry_mock():
    """Return a mock MCPToolRegistry."""
    return MagicMock()


def _make_model_mock():
    """Return a mock ChatAnthropic."""
    return MagicMock()


# ---------------------------------------------------------------------------
# G04 fix: ReactiveGraph
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_orchestrate_reactive_no_api_name_defaults_to_default():
    """Without --api-name and no servers, ReactiveGraph receives api_name='default'."""
    captured: dict = {}

    class FakeReactiveGraph:
        def __init__(self, model, registry, *, api_name: str, checkpointer=None, **kw):
            captured["api_name"] = api_name
            captured["registry"] = registry

        async def run(self, prompt, *, config=None):
            return "ok"

    with (
        patch(
            "api2mcp.orchestration.llm.LLMFactory.create",
            return_value=_make_model_mock(),
        ),
        patch(
            "api2mcp.orchestration.adapters.registry.MCPToolRegistry",
            return_value=_make_registry_mock(),
        ),
        patch(
            "api2mcp.orchestration.graphs.reactive.ReactiveGraph",
            FakeReactiveGraph,
        ),
        patch(
            "api2mcp.cli.commands.orchestrate.importlib.import_module",
            side_effect=lambda name: _fake_import(name, "ReactiveGraph", FakeReactiveGraph),
        ),
    ):
        await _run_workflow(
            prompt="test",
            graph_type="reactive",
            mode="sequential",
            provider=None,
            model_id="claude-sonnet-4-6",
            servers={},
            api_names=(),
            thread_id=None,
            stream=False,
            checkpoint_db=None,
            output_format="text",
        )

    assert captured["api_name"] == "default"
    assert captured["registry"] is not None


@pytest.mark.asyncio
async def test_orchestrate_reactive_with_api_name():
    """--api-name github passes api_name='github' to ReactiveGraph."""
    captured: dict = {}

    class FakeReactiveGraph:
        def __init__(self, model, registry, *, api_name: str, checkpointer=None, **kw):
            captured["api_name"] = api_name

        async def run(self, prompt, *, config=None):
            return "ok"

    with (
        patch("api2mcp.orchestration.llm.LLMFactory.create", return_value=_make_model_mock()),
        patch(
            "api2mcp.orchestration.adapters.registry.MCPToolRegistry",
            return_value=_make_registry_mock(),
        ),
        patch(
            "api2mcp.cli.commands.orchestrate.importlib.import_module",
            side_effect=lambda name: _fake_import(name, "ReactiveGraph", FakeReactiveGraph),
        ),
    ):
        await _run_workflow(
            prompt="test",
            graph_type="reactive",
            mode="sequential",
            provider=None,
            model_id="claude-sonnet-4-6",
            servers={},
            api_names=("github",),
            thread_id=None,
            stream=False,
            checkpoint_db=None,
            output_format="text",
        )

    assert captured["api_name"] == "github"


@pytest.mark.asyncio
async def test_orchestrate_reactive_server_fallback():
    """Without --api-name but with a named server, api_name falls back to server key."""
    captured: dict = {}

    class FakeReactiveGraph:
        def __init__(self, model, registry, *, api_name: str, checkpointer=None, **kw):
            captured["api_name"] = api_name

        async def run(self, prompt, *, config=None):
            return "ok"

    with (
        patch("api2mcp.orchestration.llm.LLMFactory.create", return_value=_make_model_mock()),
        patch(
            "api2mcp.orchestration.adapters.registry.MCPToolRegistry",
            return_value=_make_registry_mock(),
        ),
        patch(
            "api2mcp.cli.commands.orchestrate.importlib.import_module",
            side_effect=lambda name: _fake_import(name, "ReactiveGraph", FakeReactiveGraph),
        ),
    ):
        await _run_workflow(
            prompt="test",
            graph_type="reactive",
            mode="sequential",
            provider=None,
            model_id="claude-sonnet-4-6",
            servers={"myapi": "http://localhost:8001"},
            api_names=(),
            thread_id=None,
            stream=False,
            checkpoint_db=None,
            output_format="text",
        )

    assert captured["api_name"] == "myapi"


# ---------------------------------------------------------------------------
# G04 fix: PlannerGraph
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_orchestrate_planner_gets_api_names_list():
    """PlannerGraph receives a list of api_names."""
    captured: dict = {}

    class FakePlannerGraph:
        def __init__(self, model, registry, *, api_names: list, checkpointer=None, **kw):
            captured["api_names"] = api_names

        async def run(self, prompt, *, config=None):
            return "ok"

    with (
        patch("api2mcp.orchestration.llm.LLMFactory.create", return_value=_make_model_mock()),
        patch(
            "api2mcp.orchestration.adapters.registry.MCPToolRegistry",
            return_value=_make_registry_mock(),
        ),
        patch(
            "api2mcp.cli.commands.orchestrate.importlib.import_module",
            side_effect=lambda name: _fake_import(name, "PlannerGraph", FakePlannerGraph),
        ),
    ):
        await _run_workflow(
            prompt="test",
            graph_type="planner",
            mode="sequential",
            provider=None,
            model_id="claude-sonnet-4-6",
            servers={},
            api_names=("github", "jira"),
            thread_id=None,
            stream=False,
            checkpoint_db=None,
            output_format="text",
        )

    assert captured["api_names"] == ["github", "jira"]


@pytest.mark.asyncio
async def test_orchestrate_planner_mode_forwarded():
    """--mode parallel is forwarded to PlannerGraph as execution_mode."""
    captured: dict = {}

    class FakePlannerGraph:
        def __init__(self, model, registry, *, api_names: list, execution_mode: str = "sequential", checkpointer=None, **kw):
            captured["execution_mode"] = execution_mode

        async def run(self, prompt, *, config=None):
            return "ok"

    with (
        patch("api2mcp.orchestration.llm.LLMFactory.create", return_value=_make_model_mock()),
        patch(
            "api2mcp.orchestration.adapters.registry.MCPToolRegistry",
            return_value=_make_registry_mock(),
        ),
        patch(
            "api2mcp.cli.commands.orchestrate.importlib.import_module",
            side_effect=lambda name: _fake_import(name, "PlannerGraph", FakePlannerGraph),
        ),
    ):
        await _run_workflow(
            prompt="test",
            graph_type="planner",
            mode="parallel",
            provider=None,
            model_id="claude-sonnet-4-6",
            servers={},
            api_names=("github",),
            thread_id=None,
            stream=False,
            checkpoint_db=None,
            output_format="text",
        )

    assert captured["execution_mode"] == "parallel"


@pytest.mark.asyncio
async def test_orchestrate_planner_no_api_names_defaults_to_default():
    """PlannerGraph without api_names or servers defaults to ['default']."""
    captured: dict = {}

    class FakePlannerGraph:
        def __init__(self, model, registry, *, api_names: list, checkpointer=None, **kw):
            captured["api_names"] = api_names

        async def run(self, prompt, *, config=None):
            return "ok"

    with (
        patch("api2mcp.orchestration.llm.LLMFactory.create", return_value=_make_model_mock()),
        patch(
            "api2mcp.orchestration.adapters.registry.MCPToolRegistry",
            return_value=_make_registry_mock(),
        ),
        patch(
            "api2mcp.cli.commands.orchestrate.importlib.import_module",
            side_effect=lambda name: _fake_import(name, "PlannerGraph", FakePlannerGraph),
        ),
    ):
        await _run_workflow(
            prompt="test",
            graph_type="planner",
            mode="sequential",
            provider=None,
            model_id="claude-sonnet-4-6",
            servers={},
            api_names=(),
            thread_id=None,
            stream=False,
            checkpoint_db=None,
            output_format="text",
        )

    assert captured["api_names"] == ["default"]


# ---------------------------------------------------------------------------
# G04 fix: ConversationalGraph
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_orchestrate_conversational_no_api_names():
    """ConversationalGraph with no api_names receives api_names=None."""
    captured: dict = {}

    class FakeConversationalGraph:
        def __init__(self, model, registry, *, api_names=None, checkpointer=None, **kw):
            captured["api_names"] = api_names

        async def run(self, prompt, *, config=None):
            return "ok"

    with (
        patch("api2mcp.orchestration.llm.LLMFactory.create", return_value=_make_model_mock()),
        patch(
            "api2mcp.orchestration.adapters.registry.MCPToolRegistry",
            return_value=_make_registry_mock(),
        ),
        patch(
            "api2mcp.cli.commands.orchestrate.importlib.import_module",
            side_effect=lambda name: _fake_import(
                name, "ConversationalGraph", FakeConversationalGraph
            ),
        ),
    ):
        await _run_workflow(
            prompt="test",
            graph_type="conversational",
            mode="sequential",
            provider=None,
            model_id="claude-sonnet-4-6",
            servers={},
            api_names=(),
            thread_id=None,
            stream=False,
            checkpoint_db=None,
            output_format="text",
        )

    assert captured["api_names"] is None


@pytest.mark.asyncio
async def test_orchestrate_conversational_with_api_names():
    """ConversationalGraph with api_names receives the list."""
    captured: dict = {}

    class FakeConversationalGraph:
        def __init__(self, model, registry, *, api_names=None, checkpointer=None, **kw):
            captured["api_names"] = api_names

        async def run(self, prompt, *, config=None):
            return "ok"

    with (
        patch("api2mcp.orchestration.llm.LLMFactory.create", return_value=_make_model_mock()),
        patch(
            "api2mcp.orchestration.adapters.registry.MCPToolRegistry",
            return_value=_make_registry_mock(),
        ),
        patch(
            "api2mcp.cli.commands.orchestrate.importlib.import_module",
            side_effect=lambda name: _fake_import(
                name, "ConversationalGraph", FakeConversationalGraph
            ),
        ),
    ):
        await _run_workflow(
            prompt="test",
            graph_type="conversational",
            mode="sequential",
            provider=None,
            model_id="claude-sonnet-4-6",
            servers={},
            api_names=("support",),
            thread_id=None,
            stream=False,
            checkpoint_db=None,
            output_format="text",
        )

    assert captured["api_names"] == ["support"]


# ---------------------------------------------------------------------------
# Server parse error (CLI-level)
# ---------------------------------------------------------------------------

def test_orchestrate_server_parse_error():
    """--server without '=' raises UsageError (exit_code != 0)."""
    runner = CliRunner()
    result = runner.invoke(orchestrate_cmd, ["hello", "--server", "invalid"])
    assert result.exit_code != 0


# ---------------------------------------------------------------------------
# Registry is always a real MCPToolRegistry, never None
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_orchestrate_registry_is_never_none():
    """_run_workflow always passes a real MCPToolRegistry, not None."""
    captured: dict = {}

    class FakeReactiveGraph:
        def __init__(self, model, registry, *, api_name: str, checkpointer=None, **kw):
            captured["registry"] = registry

        async def run(self, prompt, *, config=None):
            return "ok"

    fake_registry = MagicMock()

    with (
        patch("api2mcp.orchestration.llm.LLMFactory.create", return_value=_make_model_mock()),
        patch(
            "api2mcp.orchestration.adapters.registry.MCPToolRegistry",
            return_value=fake_registry,
        ),
        patch(
            "api2mcp.cli.commands.orchestrate.importlib.import_module",
            side_effect=lambda name: _fake_import(name, "ReactiveGraph", FakeReactiveGraph),
        ),
    ):
        await _run_workflow(
            prompt="test",
            graph_type="reactive",
            mode="sequential",
            provider=None,
            model_id="claude-sonnet-4-6",
            servers={},
            api_names=(),
            thread_id=None,
            stream=False,
            checkpoint_db=None,
            output_format="text",
        )

    assert captured["registry"] is not None


# ---------------------------------------------------------------------------
# Internal helper — mimics importlib.import_module for a single class
# ---------------------------------------------------------------------------

def _fake_import(module_name: str, class_name: str, fake_cls):
    """Return a fake module containing *fake_cls* under *class_name*."""
    mod = MagicMock()
    setattr(mod, class_name, fake_cls)
    return mod
