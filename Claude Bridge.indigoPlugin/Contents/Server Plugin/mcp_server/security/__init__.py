"""
Security module for MCP server authentication.
"""

from .auth_manager import AuthManager
from .rate_limiter  import RateLimiter, RateLimitExceeded
from .scope_manager import ScopeManager, ScopeDenied, required_scope_for

# AccessMode enum for backward compatibility
from enum import Enum

class AccessMode(Enum):
    """Access mode for MCP server."""
    LOCAL_ONLY = "local_only"
    REMOTE_ACCESS = "remote_access"

__all__ = [
    "AuthManager", "AccessMode",
    "RateLimiter", "RateLimitExceeded",
    "ScopeManager", "ScopeDenied", "required_scope_for",
]