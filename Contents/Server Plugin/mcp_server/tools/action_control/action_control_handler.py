"""
Action control handler for MCP server.
"""

import logging
from typing import Dict, Any, Optional

from ...adapters.data_provider import DataProvider
from ..base_handler import BaseToolHandler


class ActionControlHandler(BaseToolHandler):
    """Handler for action group control operations."""
    
    def __init__(
        self,
        data_provider: DataProvider,
        logger: Optional[logging.Logger] = None
    ):
        """
        Initialize the action control handler.
        
        Args:
            data_provider: Data provider for action operations
            logger: Optional logger instance
        """
        super().__init__(tool_name="action_control", logger=logger)
        self.data_provider = data_provider
    
    def execute(self, action_group_id: int, delay: Optional[int] = None) -> Dict[str, Any]:
        """
        Execute an action group.

        Args:
            action_group_id: The action group ID to execute
            delay: Optional delay in seconds before execution

        Returns:
            Dictionary with operation results
        """
        try:
            # Validate action_group_id
            if not isinstance(action_group_id, int):
                self.info_log("❌ Invalid action_group_id type")
                return {"error": "action_group_id must be an integer", "success": False}

            # Validate delay if provided
            if delay is not None:
                if not isinstance(delay, int) or delay < 0:
                    self.info_log("❌ Invalid delay value")
                    return {"error": "delay must be a non-negative integer", "success": False}

            # Get action group name
            action_group = self.data_provider.get_action_group(action_group_id)
            action_name = action_group.get('name', f'ID {action_group_id}') if action_group else f'ID {action_group_id}'

            # Execute the action group
            result = self.data_provider.execute_action_group(action_group_id, delay)

            if result.get("success"):
                delay_str = f" (delay: {delay}s)" if delay else ""
                self.info_log(f"▶️ {action_name}{delay_str}")
            else:
                error_msg = result.get('error', 'unknown error')
                self.info_log(f"❌ {action_name}: {error_msg}")

            return result

        except Exception as e:
            return self.handle_exception(e, f"executing action group ID {action_group_id}")