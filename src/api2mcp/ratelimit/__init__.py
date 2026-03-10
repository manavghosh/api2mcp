# SPDX-License-Identifier: MIT
"""Rate limiting for API2MCP tool calls.

Provides token-bucket rate limiting, upstream header parsing, and automatic
retry with exponential backoff.

Quick start::

    from api2mcp.ratelimit import RateLimitConfig, RateLimitMiddleware

    config = RateLimitConfig(max_retries=3)
    middleware = RateLimitMiddleware(config)
    wrapped_handler = middleware.wrap(original_handler)
"""

from api2mcp.ratelimit.bucket import TokenBucket
from api2mcp.ratelimit.config import BucketConfig, RateLimitConfig
from api2mcp.ratelimit.exceptions import RateLimitError, UpstreamRateLimitError
from api2mcp.ratelimit.headers import RateLimitHeaders, parse_rate_limit_headers
from api2mcp.ratelimit.middleware import RateLimitMiddleware
from api2mcp.ratelimit.retry import build_retry, retry_with_backoff

__all__ = [
    # Bucket
    "TokenBucket",
    # Config
    "BucketConfig",
    "RateLimitConfig",
    # Exceptions
    "RateLimitError",
    "UpstreamRateLimitError",
    # Headers
    "RateLimitHeaders",
    "parse_rate_limit_headers",
    # Middleware
    "RateLimitMiddleware",
    # Retry
    "build_retry",
    "retry_with_backoff",
]
