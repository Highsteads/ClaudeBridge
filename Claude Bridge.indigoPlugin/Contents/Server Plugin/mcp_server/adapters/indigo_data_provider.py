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

    # ── Extended device control ────────────────────────────────────────────

    def set_heat_setpoint(self, device_id: int, setpoint: float) -> Dict[str, Any]:
        """Set heat setpoint on a thermostat device."""
        try:
            if device_id not in indigo.devices:
                return {"error": f"Device {device_id} not found", "success": False}
            dev = indigo.devices[device_id]
            previous = dev.heatSetpoint if hasattr(dev, 'heatSetpoint') else None
            indigo.thermostat.setHeatSetpoint(device_id, value=float(setpoint))
            dev = indigo.devices[device_id]
            current = dev.heatSetpoint if hasattr(dev, 'heatSetpoint') else setpoint
            self.logger.info(f"Set heat setpoint '{dev.name}': {previous} -> {current} degC")
            return {"success": True, "device_name": dev.name,
                    "previous": previous, "current": current}
        except Exception as e:
            self.logger.error(f"Error setting heat setpoint on {device_id}: {e}")
            return {"error": str(e), "success": False}

    def set_cool_setpoint(self, device_id: int, setpoint: float) -> Dict[str, Any]:
        """Set cool setpoint on a thermostat device."""
        try:
            if device_id not in indigo.devices:
                return {"error": f"Device {device_id} not found", "success": False}
            dev = indigo.devices[device_id]
            previous = dev.coolSetpoint if hasattr(dev, 'coolSetpoint') else None
            indigo.thermostat.setCoolSetpoint(device_id, value=float(setpoint))
            dev = indigo.devices[device_id]
            current = dev.coolSetpoint if hasattr(dev, 'coolSetpoint') else setpoint
            self.logger.info(f"Set cool setpoint '{dev.name}': {previous} -> {current} degC")
            return {"success": True, "device_name": dev.name,
                    "previous": previous, "current": current}
        except Exception as e:
            self.logger.error(f"Error setting cool setpoint on {device_id}: {e}")
            return {"error": str(e), "success": False}

    def set_hvac_mode(self, device_id: int, mode: str) -> Dict[str, Any]:
        """Set HVAC mode on a thermostat device."""
        _MODE_MAP = {
            "off":         indigo.kHvacMode.Off,
            "heat":        indigo.kHvacMode.Heat,
            "cool":        indigo.kHvacMode.Cool,
            "auto":        indigo.kHvacMode.HeatCool,
            "heatcool":    indigo.kHvacMode.HeatCool,
            "programheat": indigo.kHvacMode.ProgramHeat,
            "programcool": indigo.kHvacMode.ProgramCool,
            "programauto": indigo.kHvacMode.ProgramAuto,
        }
        mode_key = mode.lower().replace(" ", "")
        if mode_key not in _MODE_MAP:
            return {"error": f"Unknown HVAC mode '{mode}'. Valid: {list(_MODE_MAP.keys())}",
                    "success": False}
        try:
            if device_id not in indigo.devices:
                return {"error": f"Device {device_id} not found", "success": False}
            dev = indigo.devices[device_id]
            indigo.thermostat.setHvacMode(device_id, value=_MODE_MAP[mode_key])
            self.logger.info(f"Set HVAC mode '{dev.name}' -> {mode}")
            return {"success": True, "device_name": dev.name, "mode": mode}
        except Exception as e:
            self.logger.error(f"Error setting HVAC mode on {device_id}: {e}")
            return {"error": str(e), "success": False}

    def lock_device(self, device_id: int) -> Dict[str, Any]:
        """Lock a lock device."""
        try:
            if device_id not in indigo.devices:
                return {"error": f"Device {device_id} not found", "success": False}
            dev = indigo.devices[device_id]
            previous = dev.onState  # locked = onState True for lock devices
            indigo.device.lock(device_id)
            dev = indigo.devices[device_id]
            self.logger.info(f"Locked '{dev.name}'")
            return {"success": True, "device_name": dev.name,
                    "previous": previous, "current": dev.onState}
        except Exception as e:
            self.logger.error(f"Error locking device {device_id}: {e}")
            return {"error": str(e), "success": False}

    def unlock_device(self, device_id: int, code: str = None) -> Dict[str, Any]:
        """Unlock a lock device."""
        try:
            if device_id not in indigo.devices:
                return {"error": f"Device {device_id} not found", "success": False}
            dev = indigo.devices[device_id]
            previous = dev.onState
            if code:
                indigo.device.unlock(device_id, code=code)
            else:
                indigo.device.unlock(device_id)
            dev = indigo.devices[device_id]
            self.logger.info(f"Unlocked '{dev.name}'")
            return {"success": True, "device_name": dev.name,
                    "previous": previous, "current": dev.onState}
        except Exception as e:
            self.logger.error(f"Error unlocking device {device_id}: {e}")
            return {"error": str(e), "success": False}

    def set_color(self, device_id: int, red: int, green: int, blue: int,
                  white: int = None, white_temperature: int = None) -> Dict[str, Any]:
        """Set colour levels on an RGB/RGBW dimmer (values 0-255)."""
        try:
            if device_id not in indigo.devices:
                return {"error": f"Device {device_id} not found", "success": False}
            dev = indigo.devices[device_id]
            kwargs = {
                "rLevel": max(0, min(255, int(red))),
                "gLevel": max(0, min(255, int(green))),
                "bLevel": max(0, min(255, int(blue))),
            }
            if white is not None:
                kwargs["whiteLevel"] = max(0, min(255, int(white)))
            if white_temperature is not None:
                kwargs["whiteTemperature"] = int(white_temperature)
            indigo.dimmer.setColorLevels(device_id, **kwargs)
            self.logger.info(f"Set colour '{dev.name}' -> R{red} G{green} B{blue}")
            return {"success": True, "device_name": dev.name, **kwargs}
        except Exception as e:
            self.logger.error(f"Error setting colour on {device_id}: {e}")
            return {"error": str(e), "success": False}

    def set_fan_speed(self, device_id: int, speed: int) -> Dict[str, Any]:
        """Set speed on a speed-control device (0-100)."""
        try:
            if device_id not in indigo.devices:
                return {"error": f"Device {device_id} not found", "success": False}
            dev = indigo.devices[device_id]
            speed_val = max(0, min(100, int(speed)))
            previous = dev.speedLevel if hasattr(dev, 'speedLevel') else None
            indigo.speedcontrol.setSpeedLevel(device_id, value=speed_val)
            dev = indigo.devices[device_id]
            current = dev.speedLevel if hasattr(dev, 'speedLevel') else speed_val
            self.logger.info(f"Set fan speed '{dev.name}': {previous} -> {current}%")
            return {"success": True, "device_name": dev.name,
                    "previous": previous, "current": current}
        except Exception as e:
            self.logger.error(f"Error setting fan speed on {device_id}: {e}")
            return {"error": str(e), "success": False}

    def request_status_update(self, device_id: int) -> Dict[str, Any]:
        """Request a status update from a device."""
        try:
            if device_id not in indigo.devices:
                return {"error": f"Device {device_id} not found", "success": False}
            dev = indigo.devices[device_id]
            indigo.device.statusRequest(device_id)
            self.logger.info(f"Status requested for '{dev.name}'")
            return {"success": True, "device_name": dev.name}
        except Exception as e:
            self.logger.error(f"Error requesting status for {device_id}: {e}")
            return {"error": str(e), "success": False}

    def increase_heat_setpoint(self, device_id: int, delta: float = 0.5) -> Dict[str, Any]:
        """Increase the heat setpoint by delta degrees Celsius."""
        try:
            if device_id not in indigo.devices:
                return {"error": f"Device {device_id} not found", "success": False}
            dev = indigo.devices[device_id]
            previous = dev.heatSetpoint if hasattr(dev, 'heatSetpoint') else None
            if previous is None:
                return {"error": f"Device '{dev.name}' has no heat setpoint", "success": False}
            new_setpoint = round(float(previous) + float(delta), 1)
            indigo.thermostat.setHeatSetpoint(device_id, value=new_setpoint)
            dev = indigo.devices[device_id]
            current = dev.heatSetpoint if hasattr(dev, 'heatSetpoint') else new_setpoint
            self.logger.info(f"Increased heat setpoint '{dev.name}': {previous} -> {current} degC")
            return {"success": True, "device_name": dev.name,
                    "previous": previous, "current": current, "delta": delta}
        except Exception as e:
            self.logger.error(f"Error increasing heat setpoint on {device_id}: {e}")
            return {"error": str(e), "success": False}

    def decrease_heat_setpoint(self, device_id: int, delta: float = 0.5) -> Dict[str, Any]:
        """Decrease the heat setpoint by delta degrees Celsius."""
        try:
            if device_id not in indigo.devices:
                return {"error": f"Device {device_id} not found", "success": False}
            dev = indigo.devices[device_id]
            previous = dev.heatSetpoint if hasattr(dev, 'heatSetpoint') else None
            if previous is None:
                return {"error": f"Device '{dev.name}' has no heat setpoint", "success": False}
            new_setpoint = round(float(previous) - float(delta), 1)
            indigo.thermostat.setHeatSetpoint(device_id, value=new_setpoint)
            dev = indigo.devices[device_id]
            current = dev.heatSetpoint if hasattr(dev, 'heatSetpoint') else new_setpoint
            self.logger.info(f"Decreased heat setpoint '{dev.name}': {previous} -> {current} degC")
            return {"success": True, "device_name": dev.name,
                    "previous": previous, "current": current, "delta": delta}
        except Exception as e:
            self.logger.error(f"Error decreasing heat setpoint on {device_id}: {e}")
            return {"error": str(e), "success": False}

    def get_device_by_name(self, name: str) -> Optional[Dict[str, Any]]:
        """Find a device by exact or case-insensitive name match, return full state dict."""
        try:
            name_stripped = name.strip()
            name_lower    = name_stripped.lower()
            # Try exact match first
            for dev in indigo.devices:
                if dev.name == name_stripped:
                    return dict(dev)
            # Fallback: case-insensitive
            for dev in indigo.devices:
                if dev.name.lower() == name_lower:
                    return dict(dev)
            # Partial match
            for dev in indigo.devices:
                if name_lower in dev.name.lower():
                    return dict(dev)
            return None
        except Exception as e:
            self.logger.error(f"Error finding device by name '{name}': {e}")
            return None

    def log_message(self, message: str, level: str = "INFO") -> Dict[str, Any]:
        """Write a message to the Indigo on-screen event log."""
        try:
            level_upper = (level or "INFO").upper()
            if level_upper == "ERROR":
                indigo.server.log(message, level=level_upper, isError=True)
            else:
                indigo.server.log(message, level=level_upper)
            return {"success": True, "message": message, "level": level_upper}
        except Exception as e:
            self.logger.error(f"Error writing to Indigo log: {e}")
            return {"error": str(e), "success": False}

    def send_notification(
        self,
        title: str,
        message: str,
        priority: str = "0",
        sound: str = "vibrate",
    ) -> Dict[str, Any]:
        """Send a Pushover push notification via the Pushover plugin."""
        try:
            pushover = indigo.server.getPlugin("io.thechad.indigoplugin.pushover")
            if not pushover or not pushover.isEnabled():
                return {"error": "Pushover plugin not found or not enabled", "success": False}
            pushover.executeAction("send", props={
                "msgTitle":    title,
                "msgBody":     message,
                "msgPriority": str(priority),
                "msgSound":    sound,
            })
            self.logger.info(f"Pushover sent: '{title}'")
            return {"success": True, "title": title, "priority": priority, "sound": sound}
        except Exception as e:
            self.logger.error(f"Error sending Pushover notification: {e}")
            return {"error": str(e), "success": False}

    def send_email(
        self,
        recipient: str,
        subject: str,
        body: str,
    ) -> Dict[str, Any]:
        """Send an email via Indigo's configured SMTP device."""
        try:
            indigo.server.sendEmailTo(recipient, subject=subject, body=body)
            self.logger.info(f"Email sent to {recipient}: '{subject}'")
            return {"success": True, "recipient": recipient, "subject": subject}
        except Exception as e:
            self.logger.error(f"Error sending email to {recipient}: {e}")
            return {"error": str(e), "success": False}