"""Tests for observability module — graceful no-op without opentelemetry."""
from __future__ import annotations


def test_tracing_importable():
    from api2mcp.observability import tracing
    assert tracing is not None


def test_get_tracer_returns_object():
    from api2mcp.observability.tracing import get_tracer
    tracer = get_tracer("test.tracer")
    assert tracer is not None


def test_span_context_manager_no_raise():
    from api2mcp.observability.tracing import span
    with span("test_operation", tool="test_tool") as s:
        pass  # Should not raise regardless of otel installation


def test_metrics_importable():
    from api2mcp.observability import metrics
    assert metrics is not None


def test_record_tool_call_no_raise():
    from api2mcp.observability.metrics import record_tool_call
    record_tool_call(
        tool_name="github:list_issues",
        server="github",
        status="ok",
        latency_ms=42.5,
    )  # should not raise


def test_setup_tracing_no_raise():
    from api2mcp.observability.tracing import setup_tracing
    setup_tracing(service_name="test-service")  # no-ops without otel installed


def test_all_observability_exports():
    from api2mcp import observability
    assert hasattr(observability, "tracing")
    assert hasattr(observability, "metrics")
