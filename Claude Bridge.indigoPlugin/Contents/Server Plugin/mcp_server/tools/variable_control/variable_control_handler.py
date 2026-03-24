"""
Variable control handler for MCP server.
"""

import logging
from typing import Dict, Any, Optional, Union

from ...adapters.data_provider import DataProvider
from ..base_handler import BaseToolHandler


class VariableControlHandler(BaseToolHandler):
    """Handler for variable control operations."""
    
    def __init__(
        self,
        data_provider: DataProvider,
        logger: Optional[logging.Logger] = None
    ):
        """
        Initialize the variable control handler.
        
        Args:
            data_provider: Data provider for variable operations
            logger: Optional logger instance
        """
        super().__init__(tool_name="variable_control", logger=logger)
        self.data_provider = data_provider
    
    def update(self, variable_id: int, value: Union[str, int, float, bool]) -> Dict[str, Any]:
        """
        Update a variable's value.

        Args:
            variable_id: The variable ID
            value: The new value (string, number, or boolean)

        Returns:
            Dictionary with operation results
        """
        try:
            # Validate variable_id
            if not isinstance(variable_id, int):
                self.info_log("❌ Invalid variable_id type")
                return {"error": "variable_id must be an integer", "success": False}

            # Get variable name
            variable = self.data_provider.get_variable(variable_id)
            variable_name = variable.get('name', f'ID {variable_id}') if variable else f'ID {variable_id}'

            # Perform the update
            result = self.data_provider.update_variable(variable_id, value)

            if "error" in result:
                self.info_log(f"❌ {variable_name}: {result['error']}")
            else:
                prev = result.get('previous', '?')
                curr = result.get('current', value)
                self.info_log(f"📝 {variable_name}: {prev} → {curr}")

            return result

        except Exception as e:
            return self.handle_exception(e, f"updating variable ID {variable_id}")

    def create(
        self,
        name: str,
        value: str = "",
        folder_id: int = 0
    ) -> Dict[str, Any]:
        """
        Create a new variable.

        Args:
            name: The variable name (required)
            value: Initial value (default: empty string)
            folder_id: Folder ID for organization (default: 0 = root)

        Returns:
            Dictionary with operation results
        """
        try:
            # Validate name
            if not name or not isinstance(name, str):
                self.info_log("❌ Invalid or missing name")
                return {"error": "name is required and must be a string", "success": False}

            # Validate folder_id
            if not isinstance(folder_id, int):
                self.info_log("❌ Invalid folder_id type")
                return {"error": "folder_id must be an integer", "success": False}

            # Perform the creation
            result = self.data_provider.create_variable(name, value, folder_id)

            if "error" in result:
                self.info_log(f"❌ {name}: {result['error']}")
            else:
                var_id = result.get('variable_id', '?')
                self.info_log(f"✅ Created variable '{name}' (ID: {var_id}) = '{value}'")

            return result

        except Exception as e:
            return self.handle_exception(e, f"creating variable '{name}'")