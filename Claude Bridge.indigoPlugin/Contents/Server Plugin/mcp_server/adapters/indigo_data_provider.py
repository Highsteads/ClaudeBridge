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

from ..common.device_props import device_dict
from ..common.json_encoder import filter_json, KEYS_TO_KEEP_MINIMAL_DEVICES


def _to_variable_string(value) -> str:
    """Render a JSON value as an Indigo variable value.

    Indigo variables are ALWAYS strings. One helper for both the create and the
    update path, because they drifted: update normalised bools and null, create
    used a bare str() and wrote "True" and "None".

    - bool -> Indigo's lowercase "true"/"false"; str(True) gives "True", which no
      trigger or condition in Indigo compares against.
    - None -> "" rather than the literal "None", which nothing would expect.
    """
    if value is None:
        return ""
    if isinstance(value, bool):
        return str(value).lower()
    return str(value)


class IndigoDataProvider:
    """Data provider implementation for accessing Indigo entities."""

    # Sane client-side bounds for thermostat setpoints, in Celsius. A device
    # that reads in Fahrenheit gets the same band converted (_setpoint_band).
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
        Get all variables from Indigo with complete data (unfiltered, for the entity index).

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
        Get all devices from Indigo with complete data (unfiltered, for the entity index).
        
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
    
    def get_all_entities_for_index(self) -> Dict[str, List[Dict[str, Any]]]:
        """
        Get all entities, with complete data, for loading the entity index.

        Returns:
            Dictionary with 'devices', 'variables', 'actions' keys
        """
        return {
            "devices": self.get_all_devices_unfiltered(),
            "variables": self.get_all_variables_unfiltered(),
            "actions": self.get_all_actions()
        }
    
    _NO_TARGET = object()

    @staticmethod
    def _values_match(current: Any, wanted: Any) -> bool:
        """Equal, allowing for float noise (a TRV reads 20.499999 for 20.5)."""
        numeric = (int, float)
        if (isinstance(current, numeric) and isinstance(wanted, numeric)
                and not isinstance(current, bool) and not isinstance(wanted, bool)):
            return abs(float(current) - float(wanted)) < 0.05
        return current == wanted

    def _poll_for_change(self, device_id: int, attr: str, previous: Any,
                         timeout: float = 0.5, interval: float = 0.05,
                         target: Any = _NO_TARGET) -> Any:
        """
        Briefly poll a device attribute for a change after issuing a command,
        instead of an unconditional full-second sleep on the synchronous IWS
        request thread. Returns as soon as the attribute differs from
        ``previous`` (or after ``timeout`` seconds), so a settled command
        returns quickly and the worker thread is not held for a fixed second.

        With ``target``, it waits for that value instead: a device that moves
        through an intermediate value has not finished just because it moved.
        """
        deadline = time.monotonic() + timeout
        current = previous
        while time.monotonic() < deadline:
            time.sleep(interval)
            try:
                current = getattr(indigo.devices[device_id], attr)
            except Exception:
                break
            if target is not self._NO_TARGET:
                if self._values_match(current, target):
                    break
            elif current != previous:
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
            
            # Coerce BEFORE comparing. A stringy "50" from a lax client raised
            # "'<=' not supported between str and int" — a cryptic TypeError in
            # place of a plain statement about the argument.
            try:
                brightness = float(brightness)
            except (TypeError, ValueError):
                return {"error": f"Invalid brightness value: {brightness!r}. "
                                 f"Must be a number, 0-1 or 0-100"}

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
            new_value = _to_variable_string(value)
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

            # Validate folder_id. bool first — it subclasses int, and folder 0 is
            # a real destination (root), so False would be silently accepted.
            if isinstance(folder_id, bool) or not isinstance(folder_id, int):
                return {"error": "folder_id must be an integer"}

            # Same normalisation as update_variable: Indigo variables are strings,
            # a bool becomes Indigo's lowercase "true"/"false" (str(True) would
            # give "True", which no trigger or condition compares against), and a
            # JSON null becomes "" rather than the literal "None". The update path
            # was fixed in v2.10.1 and the create path was missed.
            value_str = _to_variable_string(value)

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

    # ── Thermostat setpoints ──────────────────────────────────────────────
    #
    # Indigo stores setpoints in whichever unit the thermostat reports, so a
    # Fahrenheit device reads 68 where a Celsius one reads 20. The old guards
    # assumed Celsius: a Fahrenheit 70 was refused, and a delta from 68 was
    # CLAMPED to 35 without a word. The band is now chosen from the device's
    # own readings, and a value outside it is refused, never clamped.

    _SETPOINT_KINDS = {
        "heat": ("heatSetpoint", "setHeatSetpoint", "increaseHeatSetpoint",
                 "decreaseHeatSetpoint", "SETPOINT_HEAT_MIN_C", "SETPOINT_HEAT_MAX_C"),
        "cool": ("coolSetpoint", "setCoolSetpoint", "increaseCoolSetpoint",
                 "decreaseCoolSetpoint", "SETPOINT_COOL_MIN_C", "SETPOINT_COOL_MAX_C"),
    }

    # How long a setpoint, lock or speed reply waits for the device to report
    # the new value. Short, because it holds the web server's request thread.
    CONFIRM_TIMEOUT_S = 1.0

    @staticmethod
    def _numeric_readings(dev) -> List[float]:
        values: List[Any] = [getattr(dev, "heatSetpoint", None),
                             getattr(dev, "coolSetpoint", None)]
        try:
            values.extend(list(getattr(dev, "temperatures", None) or []))
        except TypeError:
            pass
        return [float(v) for v in values
                if isinstance(v, (int, float)) and not isinstance(v, bool)]

    def _setpoint_band(self, dev, kind: str):
        """(low, high, unit) for one setpoint on this device.

        Any setpoint or temperature reading above 40 means Fahrenheit (no room
        in Celsius reads that), and the Celsius band is converted. With no
        readings at all the unit is unknown, so the band spans both: from the
        Celsius floor to the Fahrenheit ceiling.
        """
        low_c = getattr(self, self._SETPOINT_KINDS[kind][4])
        high_c = getattr(self, self._SETPOINT_KINDS[kind][5])
        low_f, high_f = round(low_c * 9 / 5 + 32, 1), round(high_c * 9 / 5 + 32, 1)
        readings = self._numeric_readings(dev)
        if any(r > 40.0 for r in readings):
            return low_f, high_f, "F"
        if readings:
            return low_c, high_c, "C"
        return low_c, high_f, "unknown"

    @staticmethod
    def _band_text(low: float, high: float, unit: str) -> str:
        suffix = {"C": " degrees C", "F": " degrees F"}.get(unit, "")
        return f"{low:g}-{high:g}{suffix}"

    def _confirmed_reply(self, device_id: int, attr: str, previous: Any,
                         requested: Any, what: str) -> Dict[str, Any]:
        """Wait briefly for `attr` to reach `requested`, then report honestly.

        `confirmed` is True only when the device reads back the value asked
        for. A device that has not caught up yet is not a failure (a TRV or a
        lock can take seconds), but the reply must not present the old value as
        the result, so it says the change is not yet confirmed.
        """
        current = self._poll_for_change(device_id, attr, previous, target=requested,
                                        timeout=self.CONFIRM_TIMEOUT_S)
        dev = indigo.devices[device_id]
        confirmed = self._values_match(current, requested)
        reply = {"success": True, "device_name": dev.name, "previous": previous,
                 "requested": requested, "current": current, "confirmed": confirmed}
        if not confirmed:
            reply["note"] = (f"Command sent, but not yet confirmed: {what} still reads "
                             f"{current!r} rather than {requested!r}. The device may take "
                             f"a few seconds to report the change.")
        return reply

    def _set_setpoint(self, device_id: int, kind: str, setpoint: Any) -> Dict[str, Any]:
        attr, setter = self._SETPOINT_KINDS[kind][0], self._SETPOINT_KINDS[kind][1]
        try:
            if device_id not in indigo.devices:
                return {"error": f"Device {device_id} not found", "success": False}
            dev = indigo.devices[device_id]
            try:
                value = float(setpoint)
            except (ValueError, TypeError):
                return {"error": f"Invalid {kind} setpoint '{setpoint}' (not a number)",
                        "success": False}
            if isinstance(setpoint, bool) or value != value:
                return {"error": f"Invalid {kind} setpoint '{setpoint}' (not a number)",
                        "success": False}
            low, high, unit = self._setpoint_band(dev, kind)
            if not (low <= value <= high):
                return {"error": f"{kind.capitalize()} setpoint {value:g} is outside "
                                 f"{self._band_text(low, high, unit)}; nothing was changed",
                        "success": False}
            previous = getattr(dev, attr, None)
            getattr(indigo.thermostat, setter)(device_id, value=value)
            reply = self._confirmed_reply(device_id, attr, previous, value,
                                          f"the {kind} setpoint")
            reply["unit"] = unit
            self.logger.info(f"Set {kind} setpoint '{reply['device_name']}': "
                             f"{previous} -> {reply['current']}")
            return reply
        except Exception as e:
            self.logger.error(f"Error setting {kind} setpoint on {device_id}: {e}")
            return {"error": str(e), "success": False}

    def _nudge_setpoint(self, device_id: int, kind: str, delta: Any) -> Dict[str, Any]:
        """Move a setpoint by `delta` (signed) with Indigo's own increase and
        decrease commands. A result outside the band is refused, never clamped."""
        attr = self._SETPOINT_KINDS[kind][0]
        try:
            if device_id not in indigo.devices:
                return {"error": f"Device {device_id} not found", "success": False}
            dev = indigo.devices[device_id]
            previous = getattr(dev, attr, None)
            if not isinstance(previous, (int, float)) or isinstance(previous, bool):
                return {"error": f"Device '{dev.name}' has no {kind} setpoint", "success": False}
            try:
                step = float(delta)
            except (TypeError, ValueError):
                return {"error": f"delta must be a number, got {delta!r}", "success": False}
            if isinstance(delta, bool) or step != step or step == 0:
                return {"error": f"delta must be a non-zero number, got {delta!r}",
                        "success": False}
            target = round(float(previous) + step, 1)
            low, high, unit = self._setpoint_band(dev, kind)
            if not (low <= target <= high):
                return {"error": f"Moving the {kind} setpoint by {step:+g} would take it from "
                                 f"{previous:g} to {target:g}, outside "
                                 f"{self._band_text(low, high, unit)}; nothing was changed",
                        "success": False}
            command = self._SETPOINT_KINDS[kind][2 if step > 0 else 3]
            getattr(indigo.thermostat, command)(device_id, delta=abs(step))
            reply = self._confirmed_reply(device_id, attr, previous, target,
                                          f"the {kind} setpoint")
            reply.update({"delta": step, "unit": unit})
            self.logger.info(f"Adjusted {kind} setpoint '{reply['device_name']}': "
                             f"{previous} -> {reply['current']}")
            return reply
        except Exception as e:
            self.logger.error(f"Error adjusting {kind} setpoint on {device_id}: {e}")
            return {"error": str(e), "success": False}

    def set_heat_setpoint(self, device_id: int, setpoint: float) -> Dict[str, Any]:
        """Set heat setpoint on a thermostat device, in the device's own unit."""
        return self._set_setpoint(device_id, "heat", setpoint)

    def set_cool_setpoint(self, device_id: int, setpoint: float) -> Dict[str, Any]:
        """Set cool setpoint on a thermostat device, in the device's own unit."""
        return self._set_setpoint(device_id, "cool", setpoint)

    def increase_cool_setpoint(self, device_id: int, delta: float = 0.5) -> Dict[str, Any]:
        """Raise the cool setpoint by delta degrees."""
        return self._nudge_setpoint(device_id, "cool", abs(float(delta)))

    def decrease_cool_setpoint(self, device_id: int, delta: float = 0.5) -> Dict[str, Any]:
        """Lower the cool setpoint by delta degrees."""
        return self._nudge_setpoint(device_id, "cool", -abs(float(delta)))

    def increase_heat_setpoint(self, device_id: int, delta: float = 0.5) -> Dict[str, Any]:
        """Raise the heat setpoint by delta degrees."""
        return self._nudge_setpoint(device_id, "heat", abs(float(delta)))

    def decrease_heat_setpoint(self, device_id: int, delta: float = 0.5) -> Dict[str, Any]:
        """Lower the heat setpoint by delta degrees."""
        return self._nudge_setpoint(device_id, "heat", -abs(float(delta)))

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
        # str() first: this runs OUTSIDE the try below, so a non-string mode
        # (a number, None) raised AttributeError out of the handler instead of
        # returning the clear "unknown mode" message a caller can act on.
        mode_key = str(mode or "").lower().replace(" ", "")
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
        """Lock a lock device. For a lock, onState True means locked."""
        try:
            if device_id not in indigo.devices:
                return {"error": f"Device {device_id} not found", "success": False}
            previous = indigo.devices[device_id].onState
            indigo.device.lock(device_id)
            reply = self._confirmed_reply(device_id, "onState", previous, True, "the lock")
            self.logger.info(f"Lock command sent to '{reply['device_name']}'"
                             + ("" if reply["confirmed"] else "; not yet confirmed locked"))
            return reply
        except Exception as e:
            self.logger.error(f"Error locking device {device_id}: {e}")
            return {"error": str(e), "success": False}

    def unlock_device(self, device_id: int) -> Dict[str, Any]:
        """Unlock a lock device.

        Takes no PIN: indigo.device.unlock accepts only delay and duration, so
        the code parameter this used to pass raised a TypeError on every call
        that supplied one.
        """
        try:
            if device_id not in indigo.devices:
                return {"error": f"Device {device_id} not found", "success": False}
            previous = indigo.devices[device_id].onState
            indigo.device.unlock(device_id)
            reply = self._confirmed_reply(device_id, "onState", previous, False, "the lock")
            self.logger.info(f"Unlock command sent to '{reply['device_name']}'"
                             + ("" if reply["confirmed"] else "; not yet confirmed unlocked"))
            return reply
        except Exception as e:
            self.logger.error(f"Error unlocking device {device_id}: {e}")
            return {"error": str(e), "success": False}

    # Indigo's colour levels run 0-100 like brightness, whiteTemperature is in
    # Kelvin (official docs, dimmer setColorLevels). Callers speak RGB 0-255.
    WHITE_TEMPERATURE_MIN_K = 1200
    WHITE_TEMPERATURE_MAX_K = 15000

    @staticmethod
    def _number_in(value: Any, low: float, high: float, name: str):
        """(float, None) when value is a number in [low, high], else (None, error)."""
        if isinstance(value, bool):
            return None, f"{name} must be a number, got {value!r}"
        try:
            number = float(value)
        except (TypeError, ValueError):
            return None, f"{name} must be a number, got {value!r}"
        if number != number or not (low <= number <= high):
            return None, f"{name} must be {low:g}-{high:g}, got {value!r}"
        return number, None

    def set_color(self, device_id: int, red: int, green: int, blue: int,
                  white: int = None, white_temperature: int = None) -> Dict[str, Any]:
        """Set colour on an RGB/RGBW dimmer.

        red/green/blue are 0-255 and are scaled to Indigo's 0-100 levels;
        white is already 0-100; white_temperature is Kelvin, 1200-15000. Until
        3.0.1 this passed rLevel/gLevel/bLevel at 0-255, names setColorLevels
        does not take.
        """
        try:
            if device_id not in indigo.devices:
                return {"error": f"Device {device_id} not found", "success": False}
            dev = indigo.devices[device_id]
            kwargs: Dict[str, Any] = {}
            for name, value, key in (("red", red, "redLevel"), ("green", green, "greenLevel"),
                                     ("blue", blue, "blueLevel")):
                number, err = self._number_in(value, 0, 255, name)
                if err:
                    return {"error": err, "success": False}
                kwargs[key] = round(number / 255 * 100, 2)
            if white is not None:
                number, err = self._number_in(white, 0, 100, "white")
                if err:
                    return {"error": err, "success": False}
                kwargs["whiteLevel"] = round(number, 2)
            if white_temperature is not None:
                number, err = self._number_in(white_temperature, self.WHITE_TEMPERATURE_MIN_K,
                                              self.WHITE_TEMPERATURE_MAX_K, "white_temperature")
                if err:
                    return {"error": err, "success": False}
                kwargs["whiteTemperature"] = int(round(number))
            indigo.dimmer.setColorLevels(device_id, **kwargs)
            self.logger.info(f"Set colour '{dev.name}' -> R{red} G{green} B{blue}")
            return {"success": True, "device_name": dev.name,
                    "requested_rgb": [red, green, blue], "levels_sent": kwargs}
        except Exception as e:
            self.logger.error(f"Error setting colour on {device_id}: {e}")
            return {"error": str(e), "success": False}

    def set_fan_speed(self, device_id: int, speed: int) -> Dict[str, Any]:
        """Set speed on a speed-control device (0-100)."""
        try:
            if device_id not in indigo.devices:
                return {"error": f"Device {device_id} not found", "success": False}
            number, err = self._number_in(speed, 0, 100, "level")
            if err:
                return {"error": err, "success": False}
            speed_val = int(round(number))
            dev = indigo.devices[device_id]
            if not hasattr(dev, "speedLevel"):
                return {"error": f"Device '{dev.name}' has no speed level", "success": False}
            previous = dev.speedLevel
            indigo.speedcontrol.setSpeedLevel(device_id, value=speed_val)
            reply = self._confirmed_reply(device_id, "speedLevel", previous, speed_val,
                                          "the speed level")
            self.logger.info(f"Set fan speed '{reply['device_name']}': "
                             f"{previous} -> {reply['current']}%")
            return reply
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