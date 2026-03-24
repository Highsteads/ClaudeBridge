"""
Authentication manager for MCP server bearer token generation and validation.
"""

import secrets
import string
import logging
from typing import Optional


class AuthManager:
    """Manages bearer token generation and validation for MCP server."""
    
    def __init__(self, logger: Optional[logging.Logger] = None):
        """
        Initialize the auth manager.
        
        Args:
            logger: Optional logger instance
        """
        self.logger = logger or logging.getLogger("Plugin")
    
    def generate_bearer_token(self, length: int = 64) -> str:
        """
        Generate a cryptographically secure bearer token.
        
        Args:
            length: Length of the token (default: 64 characters)
            
        Returns:
            Generated bearer token string
        """
        # Use URL-safe characters for the token
        alphabet = string.ascii_letters + string.digits + '-_'
        token = ''.join(secrets.choice(alphabet) for _ in range(length))
        
        self.logger.debug(f"Generated new bearer token of length {length}")
        return token
    
    def validate_token_format(self, token: str) -> bool:
        """
        Validate that a token has the correct format.
        
        Args:
            token: Token to validate
            
        Returns:
            True if token format is valid, False otherwise
        """
        if not token or not isinstance(token, str):
            return False
        
        # Check length (minimum 32 characters)
        if len(token) < 32:
            return False
        
        # Check that it only contains valid characters
        valid_chars = set(string.ascii_letters + string.digits + '-_')
        return all(c in valid_chars for c in token)
    
    def create_auth_header(self, token: str) -> str:
        """
        Create authorization header value from token.
        
        Args:
            token: Bearer token
            
        Returns:
            Authorization header value
        """
        return f"Bearer {token}"