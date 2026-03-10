"""Unit tests for orchestration node functions."""
from __future__ import annotations
import pytest


def test_nodes_module_importable():
    from api2mcp.orchestration import nodes
    assert nodes is not None


def test_generate_plan_importable():
    from api2mcp.orchestration.nodes.plan_generator import generate_plan
    assert callable(generate_plan)


def test_execute_step_importable():
    from api2mcp.orchestration.nodes.plan_executor import execute_step
    assert callable(execute_step)


def test_aggregate_results_importable():
    from api2mcp.orchestration.nodes.result_aggregator import aggregate_results
    assert callable(aggregate_results)


def test_handle_error_importable():
    from api2mcp.orchestration.nodes.error_handler import handle_error
    assert callable(handle_error)


def test_request_human_review_importable():
    from api2mcp.orchestration.nodes.human_review import request_human_review
    assert callable(request_human_review)


def test_nodes_all_exported():
    from api2mcp.orchestration import nodes
    for name in ["generate_plan", "execute_step", "aggregate_results", "handle_error", "request_human_review"]:
        assert hasattr(nodes, name), f"nodes.{name} not exported"


@pytest.mark.asyncio
async def test_handle_error_sets_flags():
    from api2mcp.orchestration.nodes.error_handler import handle_error
    state = {"error": "connection refused", "prompt": "test"}
    result = await handle_error(state)
    assert result["error_handled"] is True
    assert result["should_retry"] is False


@pytest.mark.asyncio
async def test_request_human_review_sets_flag():
    from api2mcp.orchestration.nodes.human_review import request_human_review
    state = {"pending_action": "delete_all", "prompt": "test"}
    result = await request_human_review(state)
    assert result["awaiting_review"] is True
