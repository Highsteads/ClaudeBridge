"""
Indigo data provider implementation for accessing Indigo entities.
"""

try:
    import indigo
except ImportError:
    pass

import logging
import time
from typing import Dict, List, Any, Optional

from .data_provider import DataProvider
from ..common.json_encoder import filter_json, KEYS_TO_KEEP_MINIMAL_DEVICES


class IndigoDataProvider(DataProvider):
    """Data provider implementation for accessing Indigo entities."""
    
    def __init__(self, logger: Optional[logging.Logger] = None):
        """
        Initialize the Indigo data provider.
        
        Args:
            logger: Optional logger instance
        """
        self.logger = logger or logging.getLogger("Plugin")
    
    def get_all_devices(self) -> List[Dict[str, Any]]:
        """
        Get all devices from Indigo.
        
        Returns:
            List of device dictionaries with minimal fields
        """
        devices = []
        try:
            for dev_id in indigo.devices:
                dev = indigo.devices[dev_id]
                devices.append(dict(dev))
        except Exception as e:
            self.logger.error(f"Error getting all devices: {e}")
            
        # Apply filtering to return only minimal keys
        return filter_json(devices, KEYS_TO_KEEP_MINIMAL_DEVICES)
    
    def get_device(self, device_id: int) -> Optional[Dict[str, Any]]:
        """
        Get a specific device by ID.
        
        Args:
            device_id: The device ID
            
        Returns:
            Device dictionary or None if not found
        """
        try:
            if device_id in indigo.devices:
                dev = indigo.devices[device_id]
                return dict(dev)
        except Exception as e:
            self.logger.error(f"Error getting device {device_id}: {e}")
            
        return None
    
    def get_all_variables(self) -> List[Dict[str, Any]]:
        """
        Get all variables from Indigo with minimal fields for listing.

        Returns:
            List of variable dictionaries with minimal fields:
            - id: Variable ID
            - name: Variable name
            - folderName: Folder name (only if not in root, i.e., folderId != 0)
        """
        variables = []
        try:
            # Build folder lookup map for efficient folder name resolution
            folder_map = {}
            try:
                for folder in indigo.variables.folders:
                    folder_map[folder.id] = folder.name
            except Exception as folder_error:
                self.logger.error(f"Error building folder map: {folder_error}")

            # Get all variables with filtered fields
            for var_id in indigo.variables:
                var = indigo.variables[var_id]

                # Build minimal variable dict
                minimal_var = {
                    "id": var.id,
                    "name": var.name
                }

                # Add folder name if variable is not in root (folderId != 0)
                if hasattr(var, 'folderId') and var.folderId != 0:
                    folder_name = folder_map.get(var.folderId, f"Unknown Folder ({var.folderId})")
                    minimal_var["folderName"] = folder_name

                variables.append(minimal_var)

        except Exception as e:
            self.logger.error(f"Error getting all variables: {e}")

        return variables
    
    def get_variable(self, variable_id: int) -> Optional[Dict[str, Any]]:
        """
        Get a specific variable by ID.

        Args:
            variable_id: The variable ID

        Returns:
            Variable dictionary or None if not found
        """
        try:
            if variable_id in indigo.variables:
                var = indigo.variables[variable_id]
                return dict(var)
        except Exception as e:
            self.logger.error(f"Error getting variable {variable_id}: {e}")

        return None

    def get_all_variables_unfiltered(self) -> List[Dict[str, Any]]:
        """
        Get all variables from Indigo with complete data (unfiltered for vector store).

        Returns:
            List of complete variable dictionaries with all fields
        """
        variables = []
        try:
            for var_id in indigo.variables:
                var = indigo.variables[var_id]
                variables.append(dict(var))
        except Exception as e:
            self.logger.error(f"Error getting all variables (unfiltered): {e}")

        return variables

    def get_all_actions(self) -> List[Dict[str, Any]]:
        """
        Get all action groups from Indigo.
        
        Returns:
            List of action group dictionaries with standard fields
        """
        actions = []
        try:
            for action_id in indigo.actionGroups:
                action = indigo.actionGroups[action_id]
                actions.append(dict(action))
        except Exception as e:
            self.logger.error(f"Error getting all actions: {e}")
            
        return actions
    
    def get_action(self, action_id: int) -> Optional[Dict[str, Any]]:
        """
        Get a specific action group by ID.
        
        Args:
            action_id: The action group ID
            
        Returns:
            Action group dictionary or None if not found
        """
        try:
            if action_id in indigo.actionGroups:
                action = indigo.actionGroups[action_id]
                return dict(action)
        except Exception as e:
            self.logger.error(f"Error getting action {action_id}: {e}")
            
        return None
    
    def get_action_group(self, action_group_id: int) -> Optional[Dict[str, Any]]:
        """
        Get a specific action group by ID.
        
        Args:
            action_group_id: The action group ID
            
        Returns:
            Action group dictionary or None if not found
        """
        return self.get_action(action_group_id)
    
    def get_all_devices_unfiltered(self) -> List[Dict[str, Any]]:
        """
        Get all devices from Indigo with complete data (unfiltered for vector store).
        
        Returns:
            List of complete device dictionaries
        """
        devices = []
        try:
            for dev_id in indigo.devices:
                dev = indigo.devices[dev_id]
                devices.append(dict(dev))
        except Exception as e:
            self.logger.error(f"Error getting all devices (unfiltered): {e}")
            
        return devices
    
    def get_all_entities_for_vector_store(self) -> Dict[str, List[Dict[str, Any]]]:
        """
        Get all entities formatted for vector store updates with complete data.

        Returns:
            Dictionary with 'devices', 'variables', 'actions' keys
        """
        return {
            "devices": self.get_all_devices_unfiltered(),
            "variables": self.get_all_variables_unfiltered(),
            "actions": self.get_all_actions()
        }
    
    def turn_on_device(self, device_id: int) -> Dict[str, Any]:
        """
        Turn on a device.
        
        Args:
            device_id: The device ID to turn on
            
        Returns:
            Dictionary with operation results
        """
        try:
            if device_id not in indigo.devices:
                return {"error": f"Device {device_id} not found"}
            
            # Get initial device state
            device_before = indigo.devices[device_id]
            previous_state = device_before.onState
            
            # Turn on the device
            indigo.device.turnOn(device_id)
            
            # Wait 1 second for device state to update
            time.sleep(1)
            
            # Get fresh device object from Indigo to detect actual state changes
            device_after = indigo.devices[device_id]
            current_state = device_after.onState
            
            return {
                "changed": previous_state != current_state,
                "previous": previous_state,
                "current": current_state,
                "device_name": device_after.name
            }
            
        except Exception as e:
            self.logger.error(f"Error turning on device {device_id}: {e}")
            return {"error": str(e)}
    
    def turn_off_device(self, device_id: int) -> Dict[str, Any]:
        """
        Turn off a device.
        
        Args:
            device_id: The device ID to turn off
            
        Returns:
            Dictionary with operation results
        """
        try:
            if device_id not in indigo.devices:
                return {"error": f"Device {device_id} not found"}
            
            # Get initial device state
            device_before = indigo.devices[device_id]
            previous_state = device_before.onState
            
            # Turn off the device
            indigo.device.turnOff(device_id)
            
            # Wait 1 second for device state to update
            time.sleep(1)
            
            # Get fresh device object from Indigo to detect actual state changes
            device_after = indigo.devices[device_id]
            current_state = device_after.onState
            
            return {
                "changed": previous_state != current_state,
                "previous": previous_state,
                "current": current_state,
                "device_name": device_after.name
            }
            
        except Exception as e:
            self.logger.error(f"Error turning off device {device_id}: {e}")
            return {"error": str(e)}
    
    def set_device_brightness(self, device_id: int, brightness: float) -> Dict[str, Any]:
        """
        Set brightness level for a dimmer device.
        
        Args:
            device_id: The device ID
            brightness: Brightness level (0-1 or 0-100)
            
        Returns:
            Dictionary with operation results
        """
        try:
            if device_id not in indigo.devices:
                return {"error": f"Device {device_id} not found"}
            
            # Get initial device state
            device_before = indigo.devices[device_id]
            
            # Check if device supports brightness
            if not hasattr(device_before, 'brightness'):
                return {"error": f"Device {device_id} does not support brightness control"}
            
            previous_brightness = device_before.brightness
            
            # Normalize brightness value
            # If value is between 0 and 1, convert to 0-100 range
            if 0 <= brightness <= 1:
                brightness_value = int(brightness * 100)
            elif 0 <= brightness <= 100:
                brightness_value = int(brightness)
            else:
                return {"error": f"Invalid brightness value: {brightness}. Must be 0-1 or 0-100"}
            
            # Set brightness
            indigo.dimmer.setBrightness(device_id, value=brightness_value)
            
            # Wait 1 second for device state to update
            time.sleep(1)
            
            # Get fresh device object from Indigo to detect actual state changes
            device_after = indigo.devices[device_id]
            current_brightness = device_after.brightness
            
            return {
                "changed": previous_brightness != current_brightness,
                "previous": previous_brightness,
                "current": current_brightness,
                "device_name": device_after.name
            }
            
        except Exception as e:
            self.logger.error(f"Error setting brightness for device {device_id}: {e}")
            return {"error": str(e)}
    
    def update_variable(self, variable_id: int, value: Any) -> Dict[str, Any]:
        """
        Update a variable's value.
        
        Args:
            variable_id: The variable ID
            value: The new value
            
        Returns:
            Dictionary with operation results
        """
        try:
            if variable_id not in indigo.variables:
                return {"error": f"Variable {variable_id} not found"}
            
            variable = indigo.variables[variable_id]
            
            # Check if variable is read-only
            if hasattr(variable, 'readOnly') and variable.readOnly:
                return {"error": f"Variable {variable_id} is read-only"}
            
            previous_value = variable.value
            
            # Update variable value - convert to string as Indigo variables are strings
            indigo.variable.updateValue(variable_id, value=str(value))
            
            # Get updated value
            variable.refreshFromServer()
            current_value = variable.value
            
            return {
                "previous": previous_value,
                "current": current_value
            }
            
        except Exception as e:
            self.logger.error(f"Error updating variable {variable_id}: {e}")
            return {"error": str(e)}
    
    def execute_action_group(self, action_group_id: int, delay: Optional[int] = None) -> Dict[str, Any]:
        """
        Execute an action group.
        
        Args:
            action_group_id: The action group ID
            delay: Optional delay in seconds before execution
            
        Returns:
            Dictionary with operation results
        """
        try:
            if action_group_id not in indigo.actionGroups:
                return {"error": f"Action group {action_group_id} not found"}
            
            # Execute action group with optional delay
            if delay and delay > 0:
                indigo.actionGroup.execute(action_group_id, delay=delay)
            else:
                indigo.actionGroup.execute(action_group_id)
            
            return {
                "success": True,
                "job_id": None  # Indigo doesn't provide job IDs for action group execution
            }
            
        except Exception as e:
            self.logger.error(f"Error executing action group {action_group_id}: {e}")
            return {"error": str(e), "success": False}

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
        try:
            # Build parameters for getEventLogList
            params = {
                "returnAsList": True,  # Always return as list for structured data
                "showTimeStamp": show_timestamp
            }

            if line_count is not None:
                params["lineCount"] = line_count

            # Get log entries from Indigo server
            log_entries = indigo.server.getEventLogList(**params)

            return log_entries if log_entries else []

        except Exception as e:
            self.logger.error(f"Error getting event log list: {e}")
            return []

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
            Dictionary with variable information or error
        """
        try:
            # Validate name
            if not name or not isinstance(name, str):
                return {"error": "Variable name is required and must be a string"}

            # Validate folder_id
            if not isinstance(folder_id, int):
                return {"error": "folder_id must be an integer"}

            # Convert value to string (Indigo variables are always strings)
            value_str = str(value) if value is not None else ""

            # Create the variable using Indigo API
            # indigo.variable.create(name, value=None, folder=0)
            new_variable = indigo.variable.create(name, value=value_str, folder=folder_id)

            # Return the created variable information
            return {
                "variable_id": new_variable.id,
                "name": new_variable.name,
                "value": new_variable.value,
                "folder_id": new_variable.folderId,
                "read_only": new_variable.readOnly if hasattr(new_variable, 'readOnly') else False
            }

        except Exception as e:
            self.logger.error(f"Error creating variable '{name}': {e}")
            return {"error": str(e)}

    def get_variable_folders(self) -> List[Dict[str, Any]]:
        """
        Get all variable folders.

        Returns:
            List of folder dictionaries with standard fields
        """
        folders = []
        try:
            for folder in indigo.variables.folders:
                folders.append({
                    "id": folder.id,
                    "name": folder.name,
                    "description": folder.description if hasattr(folder, 'description') else ""
                })
        except Exception as e:
            self.logger.error(f"Error getting variable folders: {e}")

        return folders