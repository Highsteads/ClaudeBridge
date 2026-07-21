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
from ..common.device_props import device_dict
from ..common.json_encoder import filter_json, KEYS_TO_KEEP_MINIMAL_DEVICES

# indigo.server.log(level=...) wants a Python logging int — a string is silently
# ignored and logs as Info. Map the tool's string level to the real int.
_LOG_LEVELS = {
    "DEBUG":    logging.DEBUG,
    "INFO":     logging.INFO,
    "WARNING":  logging.WARNING,
    "WARN":     logging.WARNING,
    "ERROR":    logging.ERROR,
    "CRITICAL": logging.CRITICAL,
}


class IndigoDataProvider(DataProvider):
    """Data provider implementation for accessing Indigo entities."""

    # Sane client-side bounds for thermostat setpoints (degrees Celsius).
    # Indigo / the device driver may clamp further, but this rejects absurd
    # values before they ever reach the hardware. Heat range covers a sensible
    # household band; cool allows a slightly higher ceiling.
    SETPOINT_HEAT_MIN_C = 5.0
    SETPOINT_HEAT_MAX_C = 35.0
    SETPOINT_COOL_MIN_C = 5.0
    SETPOINT_COOL_MAX_C = 40.0


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
                devices.append(device_dict(dev))
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
                return device_dict(dev)
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
                devices.append(device_dict(dev))
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
    
    def _poll_for_change(self, device_id: int, attr: str, previous: Any,
                         timeout: float = 0.5, interval: float = 0.05) -> Any:
        """
        Briefly poll a device attribute for a change after issuing a command,
        instead of an unconditional full-second sleep on the synchronous IWS
        request thread. Returns as soon as the attribute differs from
        ``previous`` (or after ``timeout`` seconds), so a settled command
        returns quickly and the worker thread is not held for a fixed second.
        """
        deadline = time.monotonic() + timeout
        current = previous
        while time.monotonic() < deadline:
            time.sleep(interval)
            try:
                current = getattr(indigo.devices[device_id], attr)
            except Exception:
                break
            if current != previous:
                break
        return current

    @staticmethod
    def _coerce_seconds(value, field: str) -> int:
        """Guarded int-coercion for delay/duration seconds (estate rule: never
        let a stringy or junk value reach arithmetic / the Indigo call)."""
        if value in (None, ""):
            return 0
        try:
            secs = int(float(value))
        except (TypeError, ValueError):
            raise ValueError(f"{field} must be a number of seconds, got {value!r}")
        if secs < 0:
            raise ValueError(f"{field} must be >= 0, got {secs}")
        return secs

    def turn_on_device(self, device_id: int, delay: int = 0,
                       duration: int = 0) -> Dict[str, Any]:
        """
        Turn on a device, optionally after `delay` seconds and/or turning it
        back off after `duration` seconds (Indigo-native timed action).

        Args:
            device_id: The device ID to turn on
            delay:     Seconds to wait before turning on (0 = immediately)
            duration:  Seconds to stay on before auto-off (0 = stay on)

        Returns:
            Dictionary with operation results
        """
        try:
            if device_id not in indigo.devices:
                return {"error": f"Device {device_id} not found"}
            delay    = self._coerce_seconds(delay, "delay")
            duration = self._coerce_seconds(duration, "duration")

            device_before = indigo.devices[device_id]
            previous_state = device_before.onState

            indigo.device.turnOn(device_id, delay=delay, duration=duration)

            if delay > 0:
                # The state won't change until the delay elapses — don't poll.
                return {
                    "scheduled": True,
                    "delay_seconds": delay,
                    "duration_seconds": duration,
                    "previous": previous_state,
                    "device_name": device_before.name,
                    "note": f"Turn-on scheduled in {delay}s"
                            + (f", auto-off after {duration}s" if duration else ""),
                }

            # Briefly poll for the state to update (early exit on change) instead
            # of an unconditional 1s sleep that would stall the IWS worker thread.
            current_state = self._poll_for_change(device_id, "onState", previous_state)
            device_after = indigo.devices[device_id]

            result = {
                "changed": previous_state != current_state,
                "previous": previous_state,
                "current": current_state,
                "device_name": device_after.name
            }
            if duration > 0:
                result["duration_seconds"] = duration
                result["note"] = f"Auto-off scheduled after {duration}s"
            return result

        except Exception as e:
            self.logger.error(f"Error turning on device {device_id}: {e}")
            return {"error": str(e)}

    def turn_off_device(self, device_id: int, delay: int = 0,
                        duration: int = 0) -> Dict[str, Any]:
        """
        Turn off a device, optionally after `delay` seconds and/or turning it
        back on after `duration` seconds (Indigo-native timed action).

        Args:
            device_id: The device ID to turn off
            delay:     Seconds to wait before turning off (0 = immediately)
            duration:  Seconds to stay off before auto-on (0 = stay off)

        Returns:
            Dictionary with operation results
        """
        try:
            if device_id not in indigo.devices:
                return {"error": f"Device {device_id} not found"}
            delay    = self._coerce_seconds(delay, "delay")
            duration = self._coerce_seconds(duration, "duration")

            device_before = indigo.devices[device_id]
            previous_state = device_before.onState

            indigo.device.turnOff(device_id, delay=delay, duration=duration)

            if delay > 0:
                return {
                    "scheduled": True,
                    "delay_seconds": delay,
                    "duration_seconds": duration,
                    "previous": previous_state,
                    "device_name": device_before.name,
                    "note": f"Turn-off scheduled in {delay}s"
                            + (f", auto-on after {duration}s" if duration else ""),
                }

            # Briefly poll for the state to update (early exit on change) instead
            # of an unconditional 1s sleep that would stall the IWS worker thread.
            current_state = self._poll_for_change(device_id, "onState", previous_state)
            device_after = indigo.devices[device_id]

            result = {
                "changed": previous_state != current_state,
                "previous": previous_state,
                "current": current_state,
                "device_name": device_after.name
            }
            if duration > 0:
                result["duration_seconds"] = duration
                result["note"] = f"Auto-on scheduled after {duration}s"
            return result

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
            
            # Normalize brightness value.
            # A strict fraction in [0, 1) is treated as 0-1 and scaled to 0-100;
            # everything from 1 upwards is treated as a 0-100 percent. This avoids
            # the boundary collision where brightness=1 was scaled to 100% (a
            # request for 1% drove the device to full brightness).
            if 0 <= brightness < 1:
                brightness_value = int(round(brightness * 100))
            elif 1 <= brightness <= 100:
                brightness_value = int(round(brightness))
            else:
                return {"error": f"Invalid brightness value: {brightness}. Must be 0-1 or 0-100"}
            
            # Set brightness
            indigo.dimmer.setBrightness(device_id, value=brightness_value)

            # Briefly poll for the level to update (early exit on change) instead
            # of an unconditional 1s sleep that would stall the IWS worker thread.
            current_brightness = self._poll_for_change(device_id, "brightness", previous_brightness)

            # Get fresh device object from Indigo for the device name
            device_after = indigo.devices[device_id]

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
            
            # Update variable value — Indigo variables are strings. Normalise a
            # bool to Indigo's lowercase convention ("true"/"false"), not Python's
            # capitalised str(True) == "True", so conditions/triggers comparing the
            # value behave consistently. A JSON null becomes an empty string, not
            # the literal "None" (which no condition would ever expect).
            if value is None:
                new_value = ""
            elif isinstance(value, bool):
                new_value = str(value).lower()
            else:
                new_value = str(value)
            indigo.variable.updateValue(variable_id, value=new_value)

            # Re-index from the server (consistent with the device methods) rather
            # than refreshing a stale local object. A concurrent delete surfaces a
            # clear message rather than a generic error.
            try:
                current_value = indigo.variables[variable_id].value
            except KeyError:
                return {"error": f"Variable {variable_id} was removed during update"}

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

            # Indigo's actionGroup.execute has NO delay parameter (signature is
            # execute(elem, event_data=None) — passing delay= raises TypeError).
            # Action groups simply can't be delay-executed via scripting, so be
            # honest rather than fail with an opaque type error. For a delayed
            # action, wrap it in a Schedule or use a device timed action.
            if delay and delay > 0:
                return {
                    "success": False,
                    "error": ("Indigo cannot execute an action group after a delay "
                              "(actionGroup.execute has no delay parameter). Run it "
                              "immediately (omit delay), or use a Schedule / a device "
                              "timed action for delayed execution."),
                }
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
                # Coerce + clamp to a sane range. A client (especially an AI)
                # may emit a stringified or out-of-range value; never forward it
                # to Indigo verbatim.
                try:
                    coerced = int(line_count)
                    params["lineCount"] = max(1, min(2000, coerced))
                except (ValueError, TypeError):
                    self.logger.warning(
                        f"Ignoring invalid line_count {line_count!r}; returning recent entries"
                    )

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
            try:
                setpoint_c = float(setpoint)
            except (ValueError, TypeError):
                return {"error": f"Invalid heat setpoint '{setpoint}' (not a number)",
                        "success": False}
            if not (self.SETPOINT_HEAT_MIN_C <= setpoint_c <= self.SETPOINT_HEAT_MAX_C):
                return {"error": f"Heat setpoint {setpoint_c} degC out of range "
                                 f"({self.SETPOINT_HEAT_MIN_C}-{self.SETPOINT_HEAT_MAX_C} degC)",
                        "success": False}
            previous = dev.heatSetpoint if hasattr(dev, 'heatSetpoint') else None
            indigo.thermostat.setHeatSetpoint(device_id, value=setpoint_c)
            dev = indigo.devices[device_id]
            # Report None (not the echoed request) when the device cannot confirm,
            # so a silent no-op is not reported as the requested value taking effect.
            confirmed = hasattr(dev, 'heatSetpoint')
            current = dev.heatSetpoint if confirmed else None
            self.logger.info(f"Set heat setpoint '{dev.name}': {previous} -> {current} degC")
            return {"success": True, "device_name": dev.name,
                    "previous": previous, "current": current, "confirmed": confirmed}
        except Exception as e:
            self.logger.error(f"Error setting heat setpoint on {device_id}: {e}")
            return {"error": str(e), "success": False}

    def set_cool_setpoint(self, device_id: int, setpoint: float) -> Dict[str, Any]:
        """Set cool setpoint on a thermostat device."""
        try:
            if device_id not in indigo.devices:
                return {"error": f"Device {device_id} not found", "success": False}
            dev = indigo.devices[device_id]
            try:
                setpoint_c = float(setpoint)
            except (ValueError, TypeError):
                return {"error": f"Invalid cool setpoint '{setpoint}' (not a number)",
                        "success": False}
            if not (self.SETPOINT_COOL_MIN_C <= setpoint_c <= self.SETPOINT_COOL_MAX_C):
                return {"error": f"Cool setpoint {setpoint_c} degC out of range "
                                 f"({self.SETPOINT_COOL_MIN_C}-{self.SETPOINT_COOL_MAX_C} degC)",
                        "success": False}
            previous = dev.coolSetpoint if hasattr(dev, 'coolSetpoint') else None
            indigo.thermostat.setCoolSetpoint(device_id, value=setpoint_c)
            dev = indigo.devices[device_id]
            # Report None (not the echoed request) when the device cannot confirm.
            confirmed = hasattr(dev, 'coolSetpoint')
            current = dev.coolSetpoint if confirmed else None
            self.logger.info(f"Set cool setpoint '{dev.name}': {previous} -> {current} degC")
            return {"success": True, "device_name": dev.name,
                    "previous": previous, "current": current, "confirmed": confirmed}
        except Exception as e:
            self.logger.error(f"Error setting cool setpoint on {device_id}: {e}")
            return {"error": str(e), "success": False}

    def _adjust_cool_setpoint(self, device_id: int, delta: float) -> Dict[str, Any]:
        """Nudge the cool setpoint by delta degrees Celsius (mirrors the heat pair)."""
        try:
            if device_id not in indigo.devices:
                return {"error": f"Device {device_id} not found", "success": False}
            dev = indigo.devices[device_id]
            previous = dev.coolSetpoint if hasattr(dev, 'coolSetpoint') else None
            if previous is None:
                return {"error": f"Device '{dev.name}' has no cool setpoint", "success": False}
            new_setpoint = round(float(previous) + float(delta), 1)
            new_setpoint = max(self.SETPOINT_COOL_MIN_C,
                               min(self.SETPOINT_COOL_MAX_C, new_setpoint))
            indigo.thermostat.setCoolSetpoint(device_id, value=new_setpoint)
            dev = indigo.devices[device_id]
            confirmed = hasattr(dev, 'coolSetpoint')
            current = dev.coolSetpoint if confirmed else None
            self.logger.info(f"Adjusted cool setpoint '{dev.name}': {previous} -> {current} degC")
            return {"success": True, "device_name": dev.name,
                    "previous": previous, "current": current, "delta": delta,
                    "confirmed": confirmed}
        except Exception as e:
            self.logger.error(f"Error adjusting cool setpoint on {device_id}: {e}")
            return {"error": str(e), "success": False}

    def increase_cool_setpoint(self, device_id: int, delta: float = 0.5) -> Dict[str, Any]:
        """Increase the cool setpoint by delta degrees Celsius."""
        return self._adjust_cool_setpoint(device_id, abs(float(delta)))

    def decrease_cool_setpoint(self, device_id: int, delta: float = 0.5) -> Dict[str, Any]:
        """Decrease the cool setpoint by delta degrees Celsius."""
        return self._adjust_cool_setpoint(device_id, -abs(float(delta)))

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
            current = dev.onState  # locked = onState True for lock devices
            # Log the observed transition rather than asserting success
            # unconditionally — a rejected code leaves the lock locked.
            # (The PIN code is deliberately never logged.)
            if current != previous:
                self.logger.info(f"Unlock command sent to '{dev.name}' (locked -> unlocked)")
            else:
                self.logger.info(f"Unlock command sent to '{dev.name}'; no state change observed")
            return {"success": True, "device_name": dev.name,
                    "previous": previous, "current": current}
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
            # Report None (not the echoed request) when the device cannot confirm.
            confirmed = hasattr(dev, 'speedLevel')
            current = dev.speedLevel if confirmed else None
            self.logger.info(f"Set fan speed '{dev.name}': {previous} -> {current}%")
            return {"success": True, "device_name": dev.name,
                    "previous": previous, "current": current, "confirmed": confirmed}
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
            # Clamp the adjusted value to the sane heat band before sending.
            new_setpoint = max(self.SETPOINT_HEAT_MIN_C,
                               min(self.SETPOINT_HEAT_MAX_C, new_setpoint))
            indigo.thermostat.setHeatSetpoint(device_id, value=new_setpoint)
            dev = indigo.devices[device_id]
            # Report None (not the echoed request) when the device cannot confirm.
            confirmed = hasattr(dev, 'heatSetpoint')
            current = dev.heatSetpoint if confirmed else None
            self.logger.info(f"Increased heat setpoint '{dev.name}': {previous} -> {current} degC")
            return {"success": True, "device_name": dev.name,
                    "previous": previous, "current": current, "delta": delta,
                    "confirmed": confirmed}
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
            # Clamp the adjusted value to the sane heat band before sending.
            new_setpoint = max(self.SETPOINT_HEAT_MIN_C,
                               min(self.SETPOINT_HEAT_MAX_C, new_setpoint))
            indigo.thermostat.setHeatSetpoint(device_id, value=new_setpoint)
            dev = indigo.devices[device_id]
            # Report None (not the echoed request) when the device cannot confirm.
            confirmed = hasattr(dev, 'heatSetpoint')
            current = dev.heatSetpoint if confirmed else None
            self.logger.info(f"Decreased heat setpoint '{dev.name}': {previous} -> {current} degC")
            return {"success": True, "device_name": dev.name,
                    "previous": previous, "current": current, "delta": delta,
                    "confirmed": confirmed}
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
                    return device_dict(dev)
            # Fallback: case-insensitive
            for dev in indigo.devices:
                if dev.name.lower() == name_lower:
                    return device_dict(dev)
            # Partial match — collect ALL substring matches so we never silently
            # return the first of several candidates (which could mutate the
            # wrong physical device). One match: return it. More than one:
            # return an ambiguity error listing the candidates to disambiguate.
            partial = [dev for dev in indigo.devices if name_lower in dev.name.lower()]
            if len(partial) == 1:
                return device_dict(partial[0])
            if len(partial) > 1:
                candidates = [{"id": dev.id, "name": dev.name} for dev in partial]
                return {
                    "error": f"Ambiguous device name '{name}': {len(partial)} devices "
                             f"match. Specify the exact name or use the device id.",
                    "candidates": candidates,
                }
            return None
        except Exception as e:
            self.logger.error(f"Error finding device by name '{name}': {e}")
            return None

    def log_message(self, message: str, level: str = "INFO") -> Dict[str, Any]:
        """Write a message to the Indigo on-screen event log."""
        try:
            level_upper = (level or "INFO").upper()
            # indigo.server.log(level=...) expects a Python logging INT. Passing a
            # STRING (e.g. "WARNING") is silently ignored and the line logs as Info
            # — so a WARNING/DEBUG request used to be echoed back as honoured while
            # the log line was actually Info. Map to the real level int; use
            # isError=True for ERROR so it renders red.
            level_int = _LOG_LEVELS.get(level_upper, logging.INFO)
            if level_upper == "ERROR":
                indigo.server.log(message, level=level_int, isError=True)
            else:
                indigo.server.log(message, level=level_int)
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