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
    
    def turn_on(self, device_id: int) -> Dict[str, Any]:
        """
        Turn on a device.

        Args:
            device_id: The device ID to turn on

        Returns:
            Dictionary with operation results
        """
        try:
            if isinstance(device_id, str) and device_id.isdigit():
                device_id = int(device_id)
            # Validate device_id
            if not isinstance(device_id, int):
                self.info_log("❌ Invalid device_id type")
                return {"error": "device_id must be an integer", "success": False}

            # Get device name
            device = self.data_provider.get_device(device_id)
            device_name = device.get('name', f'ID {device_id}') if device else f'ID {device_id}'

            result = self.data_provider.turn_on_device(device_id)

            if "error" in result:
                self.info_log(f"❌ {device_name}: {result['error']}")
            else:
                change_str = "changed" if result.get('changed', False) else "no change"
                self.info_log(f"🟢 {device_name} → on ({change_str})")

            return result

        except Exception as e:
            return self.handle_exception(e, f"turning on device ID {device_id}")
    
    def turn_off(self, device_id: int) -> Dict[str, Any]:
        """
        Turn off a device.

        Args:
            device_id: The device ID to turn off

        Returns:
            Dictionary with operation results
        """
        try:
            if isinstance(device_id, str) and device_id.isdigit():
                device_id = int(device_id)
            # Validate device_id
            if not isinstance(device_id, int):
                self.info_log("❌ Invalid device_id type")
                return {"error": "device_id must be an integer", "success": False}

            # Get device name
            device = self.data_provider.get_device(device_id)
            device_name = device.get('name', f'ID {device_id}') if device else f'ID {device_id}'

            result = self.data_provider.turn_off_device(device_id)

            if "error" in result:
                self.info_log(f"❌ {device_name}: {result['error']}")
            else:
                change_str = "changed" if result.get('changed', False) else "no change"
                self.info_log(f"🔴 {device_name} → off ({change_str})")

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
            if isinstance(device_id, str) and device_id.isdigit():
                device_id = int(device_id)
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