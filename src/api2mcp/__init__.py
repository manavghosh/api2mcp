# SPDX-License-Identifier: MIT
"""
API2MCP: Universal API to MCP Server Converter

Convert REST/GraphQL APIs to MCP servers with intelligent orchestration.
"""

__version__ = "0.1.0"

# Core (available from Phase 1)
from .cache import (
    CacheBackend,
    CacheConfig,
    CacheDirectives,
    CachedResponse,
    CacheMiddleware,
    MemoryCacheBackend,
    RedisConfig,
    cache_key,
    parse_headers,
)
from .circuitbreaker import (
    CircuitBreaker,
    CircuitBreakerConfig,
    CircuitBreakerError,
    CircuitBreakerMiddleware,
    CircuitState,
    EndpointConfig,
)
from .concurrency import (
    BatchResult,
    ConcurrencyConfig,
    ConcurrencyError,
    ConcurrencyLimiter,
    ConcurrencyMiddleware,
    ConcurrentExecutor,
    LimiterStats,
    TaskResult,
    TaskTracker,
)
from .core.ir_schema import APISpec
from .core.parser import BaseParser
from .discovery import DiscoveredSpec, DiscoveryResult, SpecDiscoverer, SpecFormat
from .generators.tool import MCPToolDef, ToolGenerator
from .orchestration.adapters.base import MCPToolAdapter
from .orchestration.adapters.registry import MCPToolRegistry
from .orchestration.checkpointing import (
    CheckpointerFactory,
    make_graph_config,
    make_thread_id,
)
from .orchestration.errors import ErrorClassification, ErrorHandler, ErrorPolicy
from .orchestration.graphs.conversational import ConversationalGraph
from .orchestration.graphs.planner import PlannerGraph
from .orchestration.graphs.reactive import ReactiveGraph

# Orchestration (LangGraph integration)
from .orchestration.llm import LLMConfigError, LLMFactory
from .orchestration.state.definitions import (
    BaseWorkflowState,
    ConversationalState,
    MultiAPIState,
    SingleAPIState,
)
from .orchestration.streaming import StreamEvent, filter_stream_events, stream_graph
from .parsers.graphql import GraphQLParser
from .parsers.openapi import OpenAPIParser
from .parsers.postman import PostmanParser
from .parsers.swagger import (
    MigrationSeverity,
    MigrationSuggestion,
    SwaggerConverter,
    SwaggerParser,
)
from .pool import (
    ConnectionPoolManager,
    HealthCheckConfig,
    HostPoolConfig,
    PoolConfig,
    PoolHealthStatus,
    RetryConfig,
)
from .ratelimit import RateLimitConfig, RateLimitError, RateLimitMiddleware
from .runtime.server import MCPServerRunner
from .runtime.transport import TransportConfig, TransportType

__all__ = [
    "APISpec",
    "BaseParser",
    "CacheBackend",
    "CachedResponse",
    "CacheConfig",
    "CacheDirectives",
    "CacheMiddleware",
    "MemoryCacheBackend",
    "RedisConfig",
    "cache_key",
    "parse_headers",
    "DiscoveredSpec",
    "DiscoveryResult",
    "GraphQLParser",
    "MCPServerRunner",
    "MCPToolDef",
    "MigrationSeverity",
    "MigrationSuggestion",
    "OpenAPIParser",
    "PostmanParser",
    "BatchResult",
    "ConcurrencyConfig",
    "ConcurrencyError",
    "ConcurrencyLimiter",
    "ConcurrencyMiddleware",
    "ConcurrentExecutor",
    "LimiterStats",
    "TaskResult",
    "TaskTracker",
    "ConnectionPoolManager",
    "HealthCheckConfig",
    "HostPoolConfig",
    "PoolConfig",
    "PoolHealthStatus",
    "RetryConfig",
    "RateLimitConfig",
    "RateLimitError",
    "RateLimitMiddleware",
    "CircuitBreaker",
    "CircuitBreakerConfig",
    "CircuitBreakerError",
    "CircuitBreakerMiddleware",
    "CircuitState",
    "EndpointConfig",
    "SpecDiscoverer",
    "SpecFormat",
    "SwaggerConverter",
    "SwaggerParser",
    "ToolGenerator",
    "TransportConfig",
    "TransportType",
    # Orchestration — LLM Factory
    "LLMFactory",
    "LLMConfigError",
    # Orchestration
    "MCPToolAdapter",
    "MCPToolRegistry",
    "ReactiveGraph",
    "PlannerGraph",
    "ConversationalGraph",
    "BaseWorkflowState",
    "SingleAPIState",
    "MultiAPIState",
    "ConversationalState",
    "ErrorClassification",
    "ErrorHandler",
    "ErrorPolicy",
    "CheckpointerFactory",
    "make_graph_config",
    "make_thread_id",
    "StreamEvent",
    "stream_graph",
    "filter_stream_events",
]
