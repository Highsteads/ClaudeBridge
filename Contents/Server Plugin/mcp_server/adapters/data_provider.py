"""
Abstract data provider interface for accessing Indigo entities.
"""

from abc import ABC, abstractmethod
from typing import Dict, List, Any, Optional


class DataProvider(ABC):
    """Abstract interface for accessing Indigo entity data."""
    
    @abstractmethod
    def get_all_devices(self) -> List[Dict[str, Any]]:
        """
        Get all devices.
        
        Returns:
            List of device dictionaries with standard fields:
            - id: Device ID
            - name: Device name
            - description: Device description
            - model: Device model
            - type: Device type ID
            - address: Device address
            - enabled: Whether device is enabled
            - states: Device states dictionary
        """
        pass
    
    @abstractmethod
    def get_device(self, device_id: int) -> Optional[Dict[str, Any]]:
        """
        Get a specific device by ID.
        
        Args:
            device_id: The device ID
            
        Returns:
            Device dictionary or None if not found
        """
        pass
    
    @abstractmethod
    def get_all_variables(self) -> List[Dict[str, Any]]:
        """
        Get all variables with minimal fields for listing.

        Returns:
            List of variable dictionaries with minimal fields:
            - id: Variable ID
            - name: Variable name
            - folderName: Folder name (only if not in root, i.e., folderId != 0)
        """
        pass
    
    @abstractmethod
    def get_variable(self, variable_id: int) -> Optional[Dict[str, Any]]:
        """
        Get a specific variable by ID.

        Args:
            variable_id: The variable ID

        Returns:
            Variable dictionary or None if not found
        """
        pass

    @abstractmethod
    def get_all_variables_unfiltered(self) -> List[Dict[str, Any]]:
        """
        Get all variables with complete data (unfiltered for vector store).

        Returns:
            List of complete variable dictionaries with all fields:
            - id: Variable ID
            - name: Variable name
            - value: Variable value
            - folderId: Folder ID
            - readOnly: Whether variable is read-only
            - All other Indigo variable properties
        """
        pass

    @abstractmethod
    def get_all_actions(self) -> List[Dict[str, Any]]:
        """
        Get all action groups.
        
        Returns:
            List of action group dictionaries with standard fields:
            - id: Action group ID
            - name: Action group name
            - folderId: Folder ID
            - description: Action group description
        """
        pass
    
    @abstractmethod
    def get_action(self, action_id: int) -> Optional[Dict[str, Any]]:
        """
        Get a specific action group by ID.
        
        Args:
            action_id: The action group ID
            
        Returns:
            Action group dictionary or None if not found
        """
        pass
    
    @abstractmethod
    def get_action_group(self, action_group_id: int) -> Optional[Dict[str, Any]]:
        """
        Get a specific action group by ID.
        
        Args:
            action_group_id: The action group ID
            
        Returns:
            Action group dictionary or None if not found
        """
        pass
    
    @abstractmethod
    def turn_on_device(self, device_id: int) -> Dict[str, Any]:
        """
        Turn on a device.
        
        Args:
            device_id: The device ID to turn on
            
        Returns:
            Dictionary with:
            - changed: Whether the state changed
            - previous: Previous state
            - current: Current state
            - error: Error message if operation failed
        """
        pass
    
    @abstractmethod
    def turn_off_device(self, device_id: int) -> Dict[str, Any]:
        """
        Turn off a device.
        
        Args:
            device_id: The device ID to turn off
            
        Returns:
            Dictionary with:
            - changed: Whether the state changed
            - previous: Previous state
            - current: Current state
            - error: Error message if operation failed
        """
        pass
    
    @abstractmethod
    def set_device_brightness(self, device_id: int, brightness: float) -> Dict[str, Any]:
        """
        Set brightness level for a dimmer device.
        
        Args:
            device_id: The device ID
            brightness: Brightness level (0-1 or 0-100)
            
        Returns:
            Dictionary with:
            - changed: Whether the brightness changed
            - previous: Previous brightness level
            - current: Current brightness level
            - error: Error message if operation failed
        """
        pass
    
    @abstractmethod
    def update_variable(self, variable_id: int, value: Any) -> Dict[str, Any]:
        """
        Update a variable's value.
        
        Args:
            variable_id: The variable ID
            value: The new value
            
        Returns:
            Dictionary with:
            - previous: Previous value
            - current: Current value
            - error: Error message if operation failed
        """
        pass
    
    @abstractmethod
    def execute_action_group(self, action_group_id: int, delay: Optional[int] = None) -> Dict[str, Any]:
        """
        Execute an action group.

        Args:
            action_group_id: The action group ID
            delay: Optional delay in seconds before execution

        Returns:
            Dictionary with:
            - success: Whether execution was successful
            - job_id: Job ID if available
            - error: Error message if operation failed
        """
        pass

    @abstractmethod
    def get_event_log_list(
        self,
        line_count: Optional[int] = None,
        show_timestamp: bool = True
    ) -> List[str]:
        """
        Get recent event log entries from Indigo server.

        Args:
            line_count: Number of log entries to return (default: all recent entries)
            show_timestamp: Include timestamps in log entries (default: True)

        Returns:
            List of log entry strings
        """
        pass

    @abstractmethod
    def create_variable(
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
            Dictionary with:
            - variable_id: The created variable's ID
            - name: Variable name
            - value: Variable value
            - folder_id: Folder ID
            - error: Error message if operation failed
        """
        pass

    @abstractmethod
    def get_variable_folders(self) -> List[Dict[str, Any]]:
        """
        Get all variable folders.

        Returns:
            List of folder dictionaries with standard fields:
            - id: Folder ID
            - name: Folder name
            - description: Folder description
        """
        pass