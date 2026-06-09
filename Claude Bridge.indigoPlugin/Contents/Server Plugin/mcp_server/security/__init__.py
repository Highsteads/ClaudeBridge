"""
Security module for MCP server authentication.

The live security model is the IWS bearer token + per-token ScopeManager +
RateLimiter + the webhook egress firewall. The former AuthManager (token
generation/format validation) and AccessMode enum were never wired into the
request path and were removed in v2.8.4 — recover from git history if a future
use is ever wanted.
"""

from .rate_limiter  import RateLimiter, RateLimitExceeded
from .scope_manager import ScopeManager, ScopeDenied, required_scope_for

__all__ = [
    "RateLimiter", "RateLimitExceeded",
    "ScopeManager", "ScopeDenied", "required_scope_for",
]