# SPDX-License-Identifier: MIT
"""OpenTelemetry tracing — gracefully no-ops if opentelemetry is not installed."""
from __future__ import annotations

import logging
from contextlib import contextmanager
from typing import Any, Generator

logger = logging.getLogger(__name__)

_otel_trace: Any = None
_HAS_OTEL = False

try:
    from opentelemetry import trace as _otel_trace  # type: ignore[import-not-found]
    _HAS_OTEL = True
except ImportError:
    pass

_tracer_provider: Any = None


def setup_tracing(
    service_name: str = "api2mcp",
    exporter: str = "console",
    endpoint: str = "http://localhost:4317",
    sample_rate: float = 1.0,
) -> None:
    """Configure the global OpenTelemetry tracer provider.

    No-ops if ``opentelemetry`` is not installed.

    Args:
        service_name: OTel resource service.name attribute.
        exporter:     Exporter type: console | otlp | jaeger | zipkin.
        endpoint:     Collector endpoint (OTLP only).
        sample_rate:  Fraction of traces to sample (0.0–1.0).
    """
    _ = endpoint, sample_rate  # reserved for future exporter configuration
    global _tracer_provider
    if not _HAS_OTEL:
        logger.debug("opentelemetry not installed — tracing disabled")
        return
    from opentelemetry.sdk.trace import TracerProvider  # type: ignore[import-not-found]
    from opentelemetry.sdk.resources import Resource  # type: ignore[import-not-found]
    resource = Resource.create({"service.name": service_name})
    _tracer_provider = TracerProvider(resource=resource)
    _otel_trace.set_tracer_provider(_tracer_provider)
    logger.info("Tracing: configured service=%r exporter=%r", service_name, exporter)


def get_tracer(name: str) -> Any:
    """Return a tracer, or a no-op stub if tracing is not configured."""
    if not _HAS_OTEL:
        return _NoOpTracer()
    return _otel_trace.get_tracer(name)


@contextmanager
def span(name: str, **attributes: Any) -> Generator[Any, None, None]:
    """Context manager that creates an OTel span, or no-ops if unavailable."""
    if not _HAS_OTEL:
        yield None
        return
    tracer = get_tracer(__name__)
    with tracer.start_as_current_span(name) as s:
        for k, v in attributes.items():
            s.set_attribute(k, str(v))
        yield s


class _NoOpTracer:
    """Tracer stub returned when opentelemetry is not installed."""

    @contextmanager
    def start_as_current_span(self, name: str, **kwargs: Any) -> Generator[None, None, None]:
        _ = name, kwargs
        yield None
