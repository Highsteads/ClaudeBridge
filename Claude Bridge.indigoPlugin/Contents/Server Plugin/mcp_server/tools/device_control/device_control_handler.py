"""
Device control handler for MCP server.
"""

import logging
from typing import Dict, Any, Optional

from ...adapters.data_provider import DataProvider
from ..base_handler import BaseToolHandler


class DeviceControlHandler(BaseToolHandler):
    """Handler for device control operations."""
    
    def __init__(
        self,
        data_provider: DataProvider,
        logger: Optional[logging.Logger] = None
    ):
        """
        Initialize the device control handler.
        
        Args:
            data_provider: Data provider for device operations
            logger: Optional logger instance
        """
        super().__init__(tool_name="device_control", logger=logger)
        self.data_provider = data_provider

    @staticmethod
    def _coerce_device_id(device_id: Any) -> Any:
        """
        Coerce a numeric-string device_id to int (the schema advertises
        anyOf number|string, and MCP clients often send IDs as strings).
        Uses a guarded int() so signs and surrounding whitespace are handled
        uniformly; a non-numeric value is returned unchanged so the caller's
        isinstance(int) check still rejects it cleanly.
        """
        # A Python bool IS an int (isinstance(True, int) is True), so a JSON
        # `true`/`false` would otherwise slip past the caller's int check and act
        # on device ID 1/0. Reject it up front by returning a non-int.
        if isinstance(device_id, bool):
            return None
        if isinstance(device_id, str):
            try:
                return int(device_id.strip())
            except (TypeError, ValueError):
                return device_id
        return device_id

    def turn_on(self, device_id: int, delay: int = 0, duration: int = 0) -> Dict[str, Any]:
        """
        Turn on a device, optionally delayed and/or for a fixed duration.

        Args:
            device_id: The device ID to turn on
            delay:     Seconds before turning on (0 = now)
            duration:  Seconds to stay on before auto-off (0 = stay on)

        Returns:
            Dictionary with operation results
        """
        try:
            device_id = self._coerce_device_id(device_id)
            # Validate device_id
            if not isinstance(device_id, int):
                self.info_log("❌ Invalid device_id type")
                return {"error": "device_id must be an integer", "success": False}

            # Get device name
            device = self.data_provider.get_device(device_id)
            device_name = device.get('name', f'ID {device_id}') if device else f'ID {device_id}'

            result = self.data_provider.turn_on_device(device_id, delay=delay,
                                                       duration=duration)

            if "error" in result:
                self.info_log(f"❌ {device_name}: {result['error']}")
            elif result.get("scheduled"):
                self.info_log(f"🕑 {device_name} → on ({result.get('note', 'scheduled')})")
            else:
                change_str = "changed" if result.get('changed', False) else "no change"
                extra = f", {result['note']}" if result.get('note') else ""
                self.info_log(f"🟢 {device_name} → on ({change_str}{extra})")

            return result

        except Exception as e:
            return self.handle_exception(e, f"turning on device ID {device_id}")

    def turn_off(self, device_id: int, delay: int = 0, duration: int = 0) -> Dict[str, Any]:
        """
        Turn off a device, optionally delayed and/or for a fixed duration.

        Args:
            device_id: The device ID to turn off
            delay:     Seconds before turning off (0 = now)
            duration:  Seconds to stay off before auto-on (0 = stay off)

        Returns:
            Dictionary with operation results
        """
        try:
            device_id = self._coerce_device_id(device_id)
            # Validate device_id
            if not isinstance(device_id, int):
                self.info_log("❌ Invalid device_id type")
                return {"error": "device_id must be an integer", "success": False}

            # Get device name
            device = self.data_provider.get_device(device_id)
            device_name = device.get('name', f'ID {device_id}') if device else f'ID {device_id}'

            result = self.data_provider.turn_off_device(device_id, delay=delay,
                                                        duration=duration)

            if "error" in result:
                self.info_log(f"❌ {device_name}: {result['error']}")
            elif result.get("scheduled"):
                self.info_log(f"🕑 {device_name} → off ({result.get('note', 'scheduled')})")
            else:
                change_str = "changed" if result.get('changed', False) else "no change"
                extra = f", {result['note']}" if result.get('note') else ""
                self.info_log(f"🔴 {device_name} → off ({change_str}{extra})")

            return result

        except Exception as e:
            return self.handle_exception(e, f"turning off device ID {device_id}")
    
    def set_brightness(self, device_id: int, brightness: float) -> Dict[str, Any]:
        """
        Set brightness level for a dimmer device.

        Args:
            device_id: The device ID
            brightness: Brightness level (0-1 or 0-100)

        Returns:
            Dictionary with operation results
        """
        try:
            device_id = self._coerce_device_id(device_id)
            # Validate device_id
            if not isinstance(device_id, int):
                self.info_log("❌ Invalid device_id type")
                return {"error": "device_id must be an integer", "success": False}

            # Validate brightness
            if not isinstance(brightness, (int, float)):
                self.info_log("❌ Invalid brightness type")
                return {"error": "brightness must be a number", "success": False}

            # Get device name
            device = self.data_provider.get_device(device_id)
            device_name = device.get('name', f'ID {device_id}') if device else f'ID {device_id}'

            result = self.data_provider.set_device_brightness(device_id, brightness)

            if "error" in result:
                self.info_log(f"❌ {device_name}: {result['error']}")
            else:
                change_str = "changed" if result.get('changed', False) else "no change"
                self.info_log(f"🔆 {device_name} → {brightness}% ({change_str})")

            return result

        except Exception as e:
            return self.handle_exception(e, f"setting brightness for device ID {device_id}")

    def set_heat_setpoint(self, device_id: int, setpoint: float) -> Dict[str, Any]:
        """Set heat setpoint on a thermostat device."""
        try:
            device_id = self._coerce_device_id(device_id)
            if not isinstance(device_id, int):
                return {"error": "device_id must be an integer", "success": False}
            result = self.data_provider.set_heat_setpoint(device_id, setpoint)
            if "error" in result:
                self.info_log(f"❌ Heat setpoint error: {result['error']}")
            else:
                self.info_log(f"🌡 {result.get('device_name', device_id)} heat setpoint → {setpoint} degC")
            return result
        except Exception as e:
            return self.handle_exception(e, f"setting heat setpoint on device ID {device_id}")

    def set_cool_setpoint(self, device_id: int, setpoint: float) -> Dict[str, Any]:
        """Set cool setpoint on a thermostat device."""
        try:
            device_id = self._coerce_device_id(device_id)
            if not isinstance(device_id, int):
                return {"error": "device_id must be an integer", "success": False}
            result = self.data_provider.set_cool_setpoint(device_id, setpoint)
            if "error" in result:
                self.info_log(f"❌ Cool setpoint error: {result['error']}")
            else:
                self.info_log(f"❄ {result.get('device_name', device_id)} cool setpoint → {setpoint} degC")
            return result
        except Exception as e:
            return self.handle_exception(e, f"setting cool setpoint on device ID {device_id}")

    def set_hvac_mode(self, device_id: int, mode: str) -> Dict[str, Any]:
        """Set HVAC mode on a thermostat device."""
        try:
            device_id = self._coerce_device_id(device_id)
            if not isinstance(device_id, int):
                return {"error": "device_id must be an integer", "success": False}
            result = self.data_provider.set_hvac_mode(device_id, mode)
            if "error" in result:
                self.info_log(f"❌ HVAC mode error: {result['error']}")
            else:
                self.info_log(f"♨ {result.get('device_name', device_id)} HVAC mode → {mode}")
            return result
        except Exception as e:
            return self.handle_exception(e, f"setting HVAC mode on device ID {device_id}")

    def lock_device(self, device_id: int) -> Dict[str, Any]:
        """Lock a lock device."""
        try:
            device_id = self._coerce_device_id(device_id)
            if not isinstance(device_id, int):
                return {"error": "device_id must be an integer", "success": False}
            result = self.data_provider.lock_device(device_id)
            if "error" in result:
                self.info_log(f"❌ Lock error: {result['error']}")
            else:
                self.info_log(f"🔒 {result.get('device_name', device_id)} → locked")
            return result
        except Exception as e:
            return self.handle_exception(e, f"locking device ID {device_id}")

    def unlock_device(self, device_id: int, code: str = None) -> Dict[str, Any]:
        """Unlock a lock device."""
        try:
            device_id = self._coerce_device_id(device_id)
            if not isinstance(device_id, int):
                return {"error": "device_id must be an integer", "success": False}
            result = self.data_provider.unlock_device(device_id, code=code)
            if "error" in result:
                self.info_log(f"❌ Unlock error: {result['error']}")
            else:
                self.info_log(f"🔓 {result.get('device_name', device_id)} → unlocked")
            return result
        except Exception as e:
            return self.handle_exception(e, f"unlocking device ID {device_id}")

    def set_color(self, device_id: int, red: int, green: int, blue: int,
                  white: int = None, white_temperature: int = None) -> Dict[str, Any]:
        """Set colour levels on an RGB/RGBW dimmer."""
        try:
            device_id = self._coerce_device_id(device_id)
            if not isinstance(device_id, int):
                return {"error": "device_id must be an integer", "success": False}
            result = self.data_provider.set_color(device_id, red, green, blue,
                                                   white=white,
                                                   white_temperature=white_temperature)
            if "error" in result:
                self.info_log(f"❌ Colour error: {result['error']}")
            else:
                self.info_log(f"🎨 {result.get('device_name', device_id)} → R{red} G{green} B{blue}")
            return result
        except Exception as e:
            return self.handle_exception(e, f"setting colour on device ID {device_id}")

    def set_fan_speed(self, device_id: int, speed: int) -> Dict[str, Any]:
        """Set speed on a speed-control device."""
        try:
            device_id = self._coerce_device_id(device_id)
            if not isinstance(device_id, int):
                return {"error": "device_id must be an integer", "success": False}
            result = self.data_provider.set_fan_speed(device_id, speed)
            if "error" in result:
                self.info_log(f"❌ Fan speed error: {result['error']}")
            else:
                self.info_log(f"💨 {result.get('device_name', device_id)} speed → {speed}%")
            return result
        except Exception as e:
            return self.handle_exception(e, f"setting fan speed on device ID {device_id}")

    def request_status_update(self, device_id: int) -> Dict[str, Any]:
        """Request a status update from a device."""
        try:
            device_id = self._coerce_device_id(device_id)
            if not isinstance(device_id, int):
                return {"error": "device_id must be an integer", "success": False}
            result = self.data_provider.request_status_update(device_id)
            if "error" in result:
                self.info_log(f"❌ Status request error: {result['error']}")
            else:
                self.info_log(f"📡 Status requested: {result.get('device_name', device_id)}")
            return result
        except Exception as e:
            return self.handle_exception(e, f"requesting status for device ID {device_id}")

    def increase_heat_setpoint(self, device_id: int, delta: float = 0.5) -> Dict[str, Any]:
        """Increase the heat setpoint by delta degrees Celsius."""
        try:
            device_id = self._coerce_device_id(device_id)
            if not isinstance(device_id, int):
                return {"error": "device_id must be an integer", "success": False}
            result = self.data_provider.increase_heat_setpoint(device_id, delta)
            if "error" in result:
                self.info_log(f"❌ Increase setpoint error: {result['error']}")
            else:
                self.info_log(
                    f"🌡 {result.get('device_name', device_id)} "
                    f"setpoint ↑ {result.get('previous')} → {result.get('current')} degC"
                )
            return result
        except Exception as e:
            return self.handle_exception(e, f"increasing heat setpoint on device ID {device_id}")

    def decrease_heat_setpoint(self, device_id: int, delta: float = 0.5) -> Dict[str, Any]:
        """Decrease the heat setpoint by delta degrees Celsius."""
        try:
            device_id = self._coerce_device_id(device_id)
            if not isinstance(device_id, int):
                return {"error": "device_id must be an integer", "success": False}
            result = self.data_provider.decrease_heat_setpoint(device_id, delta)
            if "error" in result:
                self.info_log(f"❌ Decrease setpoint error: {result['error']}")
            else:
                self.info_log(
                    f"🌡 {result.get('device_name', device_id)} "
                    f"setpoint ↓ {result.get('previous')} → {result.get('current')} degC"
                )
            return result
        except Exception as e:
            return self.handle_exception(e, f"decreasing heat setpoint on device ID {device_id}")

    def increase_cool_setpoint(self, device_id: int, delta: float = 0.5) -> Dict[str, Any]:
        """Increase the cool setpoint by delta degrees Celsius."""
        try:
            device_id = self._coerce_device_id(device_id)
            if not isinstance(device_id, int):
                return {"error": "device_id must be an integer", "success": False}
            result = self.data_provider.increase_cool_setpoint(device_id, delta)
            if "error" in result:
                self.info_log(f"❌ Increase cool setpoint error: {result['error']}")
            else:
                self.info_log(
                    f"❄️ {result.get('device_name', device_id)} "
                    f"cool setpoint ↑ {result.get('previous')} → {result.get('current')} degC"
                )
            return result
        except Exception as e:
            return self.handle_exception(e, f"increasing cool setpoint on device ID {device_id}")

    def decrease_cool_setpoint(self, device_id: int, delta: float = 0.5) -> Dict[str, Any]:
        """Decrease the cool setpoint by delta degrees Celsius."""
        try:
            device_id = self._coerce_device_id(device_id)
            if not isinstance(device_id, int):
                return {"error": "device_id must be an integer", "success": False}
            result = self.data_provider.decrease_cool_setpoint(device_id, delta)
            if "error" in result:
                self.info_log(f"❌ Decrease cool setpoint error: {result['error']}")
            else:
                self.info_log(
                    f"❄️ {result.get('device_name', device_id)} "
                    f"cool setpoint ↓ {result.get('previous')} → {result.get('current')} degC"
                )
            return result
        except Exception as e:
            return self.handle_exception(e, f"decreasing cool setpoint on device ID {device_id}")