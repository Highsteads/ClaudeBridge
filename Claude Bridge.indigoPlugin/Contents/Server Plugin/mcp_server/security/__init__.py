"""
Security module for MCP server authentication.
"""

from .auth_manager import AuthManager

# AccessMode enum for backward compatibility
from enum import Enum

class AccessMode(Enum):
    """Access mode for MCP server."""
    LOCAL_ONLY = "local_only"
    REMOTE_ACCESS = "remote_access"

__all__ = ["AuthManager", "AccessMode"]