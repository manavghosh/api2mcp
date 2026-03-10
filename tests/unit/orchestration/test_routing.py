"""Unit tests for orchestration routing functions."""
from __future__ import annotations


def test_routing_module_importable():
    from api2mcp.orchestration import routing
    assert routing is not None


def test_should_continue_with_tool_calls():
    from unittest.mock import MagicMock

    from api2mcp.orchestration.routing.should_continue import should_continue
    msg = MagicMock()
    msg.tool_calls = [{"name": "some_tool"}]
    state = {"messages": [msg]}
    assert should_continue(state) == "tools"


def test_should_continue_without_tool_calls():
    from langgraph.graph import END

    from api2mcp.orchestration.routing.should_continue import should_continue

    class FakeMsg:
        tool_calls = []

    state = {"messages": [FakeMsg()]}
    result = should_continue(state)
    assert result == END


def test_should_continue_empty_messages():
    from langgraph.graph import END

    from api2mcp.orchestration.routing.should_continue import should_continue
    state = {"messages": []}
    assert should_continue(state) == END


def test_error_router_retry():
    from api2mcp.orchestration.routing.error_router import route_on_error
    state = {"should_retry": True}
    assert route_on_error(state) == "retry"


def test_error_router_failure():
    from api2mcp.orchestration.routing.error_router import route_on_error
    state = {"should_retry": False}
    assert route_on_error(state) == "failure"


def test_plan_router_has_more_steps():
    from api2mcp.orchestration.routing.plan_router import route_plan_step
    state = {"plan_steps": ["step1", "step2", "step3"], "current_step_index": 0}
    assert route_plan_step(state) == "execute_step"


def test_plan_router_last_step():
    from api2mcp.orchestration.routing.plan_router import route_plan_step
    state = {"plan_steps": ["step1", "step2"], "current_step_index": 1}
    assert route_plan_step(state) == "aggregate"


def test_approval_router_requires_review():
    from api2mcp.orchestration.routing.approval_router import route_for_approval
    state = {"requires_approval": True}
    assert route_for_approval(state) == "human_review"


def test_approval_router_no_review():
    from api2mcp.orchestration.routing.approval_router import route_for_approval
    state = {"requires_approval": False}
    assert route_for_approval(state) == "execute"


def test_all_routing_functions_exported():
    from api2mcp.orchestration import routing
    for name in ["should_continue", "route_plan_step", "route_on_error", "route_for_approval"]:
        assert hasattr(routing, name), f"routing.{name} not exported"
