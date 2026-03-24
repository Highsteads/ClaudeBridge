"""
Device type definitions for Indigo devices.
"""

from enum import Enum
from typing import List, Dict, Any, Optional
import re


class IndigoDeviceType(str, Enum):
    """
    Enum for Indigo device types based on deviceTypeId field values.
    
    These values correspond to the deviceTypeId field found in Indigo device dictionaries
    and can be used for filtering devices by type.
    """
    DIMMER = "dimmer"
    RELAY = "relay"
    SENSOR = "sensor"
    MULTIIO = "multiio"
    SPEEDCONTROL = "speedcontrol"
    SPRINKLER = "sprinkler"
    THERMOSTAT = "thermostat"
    DEVICE = "device"  # Base device type
    
    @classmethod
    def get_all_types(cls) -> List[str]:
        """Get list of all device type values."""
        return [device_type.value for device_type in cls]
    
    @classmethod
    def is_valid_type(cls, device_type: str) -> bool:
        """Check if a device type string is valid."""
        return device_type in cls.get_all_types()


class IndigoEntityType(str, Enum):
    """Enum for Indigo entity types."""
    DEVICE = "device"
    VARIABLE = "variable"
    ACTION = "action"
    
    @classmethod
    def get_all_types(cls) -> List[str]:
        """Get list of all entity type values."""
        return [entity_type.value for entity_type in cls]
    
    @classmethod
    def is_valid_type(cls, entity_type: str) -> bool:
        """Check if an entity type string is valid."""
        return entity_type in cls.get_all_types()


class DeviceTypeResolver:
    """
    Resolves device type aliases to valid IndigoDeviceType values.

    This class provides a mapping system to convert common user-friendly device type
    names (like 'light', 'switch') to valid IndigoDeviceType enum values.
    """

    # Alias mappings - common user terms to valid device types
    DEVICE_TYPE_ALIASES = {
        # Lighting aliases
        "light": IndigoDeviceType.DIMMER,
        "lights": IndigoDeviceType.DIMMER,
        "lamp": IndigoDeviceType.DIMMER,
        "lamps": IndigoDeviceType.DIMMER,
        "bulb": IndigoDeviceType.DIMMER,
        "bulbs": IndigoDeviceType.DIMMER,

        # Switch/Relay aliases
        "switch": IndigoDeviceType.RELAY,
        "switches": IndigoDeviceType.RELAY,
        "outlet": IndigoDeviceType.RELAY,
        "outlets": IndigoDeviceType.RELAY,
        "plug": IndigoDeviceType.RELAY,
        "plugs": IndigoDeviceType.RELAY,

        # Sensor aliases
        "motion": IndigoDeviceType.SENSOR,
        "temperature": IndigoDeviceType.SENSOR,
        "humidity": IndigoDeviceType.SENSOR,
        "contact": IndigoDeviceType.SENSOR,
        "door": IndigoDeviceType.SENSOR,
        "window": IndigoDeviceType.SENSOR,
        "detector": IndigoDeviceType.SENSOR,

        # Fan/Speed control aliases
        "fan": IndigoDeviceType.SPEEDCONTROL,
        "fans": IndigoDeviceType.SPEEDCONTROL,

        # I/O aliases
        "io": IndigoDeviceType.MULTIIO,
        "input": IndigoDeviceType.MULTIIO,
        "output": IndigoDeviceType.MULTIIO,

        # HVAC aliases
        "hvac": IndigoDeviceType.THERMOSTAT,
        "climate": IndigoDeviceType.THERMOSTAT,
        "temp": IndigoDeviceType.THERMOSTAT,

        # Irrigation aliases
        "irrigation": IndigoDeviceType.SPRINKLER,
        "water": IndigoDeviceType.SPRINKLER,
        "watering": IndigoDeviceType.SPRINKLER,
    }

    @classmethod
    def resolve_device_type(cls, device_type: str) -> Optional[str]:
        """
        Resolve a device type string to a valid IndigoDeviceType value.

        Args:
            device_type: Device type string (may be alias or valid type)

        Returns:
            Valid device type string or None if not resolvable
        """
        if not device_type:
            return None

        # Convert to lowercase for case-insensitive matching
        device_type_lower = device_type.lower().strip()

        # First check if it's already a valid type
        if IndigoDeviceType.is_valid_type(device_type):
            return device_type

        # Then check aliases
        if device_type_lower in cls.DEVICE_TYPE_ALIASES:
            return cls.DEVICE_TYPE_ALIASES[device_type_lower].value

        return None

    @classmethod
    def resolve_device_types(cls, device_types: List[str]) -> tuple[List[str], List[str]]:
        """
        Resolve a list of device types, returning valid types and any unresolvable ones.

        Args:
            device_types: List of device type strings

        Returns:
            Tuple of (resolved_valid_types, unresolvable_types)
        """
        if not device_types:
            return [], []

        valid_types = []
        invalid_types = []

        for device_type in device_types:
            resolved = cls.resolve_device_type(device_type)
            if resolved:
                valid_types.append(resolved)
            else:
                invalid_types.append(device_type)

        return valid_types, invalid_types

    @classmethod
    def get_suggestions_for_invalid_type(cls, invalid_type: str) -> List[str]:
        """
        Get suggestions for an invalid device type based on similarity.

        Args:
            invalid_type: The invalid device type string

        Returns:
            List of suggested valid types/aliases
        """
        if not invalid_type:
            return []

        invalid_lower = invalid_type.lower().strip()
        suggestions = []

        # Check for partial matches in aliases
        for alias, valid_type in cls.DEVICE_TYPE_ALIASES.items():
            if invalid_lower in alias or alias in invalid_lower:
                suggestions.append(f"'{alias}' → {valid_type.value}")

        # Check for partial matches in valid types
        for valid_type in IndigoDeviceType.get_all_types():
            if invalid_lower in valid_type or valid_type in invalid_lower:
                suggestions.append(f"'{valid_type}'")

        # Remove duplicates while preserving order
        seen = set()
        unique_suggestions = []
        for suggestion in suggestions:
            if suggestion not in seen:
                seen.add(suggestion)
                unique_suggestions.append(suggestion)

        return unique_suggestions[:3]  # Limit to top 3 suggestions

    @classmethod
    def get_all_aliases(cls) -> Dict[str, str]:
        """
        Get all available aliases and their mappings.

        Returns:
            Dictionary mapping alias to valid device type
        """
        return {alias: device_type.value for alias, device_type in cls.DEVICE_TYPE_ALIASES.items()}


class DeviceClassifier:
    """
    Classifies Indigo devices into logical types based on class and deviceTypeId.

    This class handles the mapping between Indigo's specific device classes and types
    (like 'indigo.DimmerDevice', 'ra2Dimmer') to our logical device types ('dimmer', 'relay').
    """
    
    # Device class to type mappings
    CLASS_TO_TYPE_MAP = {
        "indigo.DimmerDevice": IndigoDeviceType.DIMMER,
        "indigo.RelayDevice": IndigoDeviceType.RELAY,
        "indigo.SensorDevice": IndigoDeviceType.SENSOR,
        "indigo.MultiIODevice": IndigoDeviceType.MULTIIO,
        "indigo.SpeedControlDevice": IndigoDeviceType.SPEEDCONTROL,
        "indigo.SprinklerDevice": IndigoDeviceType.SPRINKLER,
        "indigo.ThermostatDevice": IndigoDeviceType.THERMOSTAT,
        "indigo.Device": IndigoDeviceType.DEVICE,
    }
    
    # DeviceTypeId patterns that indicate specific device types
    # These are regex patterns that match common deviceTypeId values
    DEVICETYPE_PATTERNS = {
        IndigoDeviceType.DIMMER: [
            r".*[Dd]immer.*",
            r".*[Ll]ight.*",  # Many lights are dimmers
            r"hue.*",         # Hue devices are typically dimmers
            r".*[Bb]ulb.*",   # Bulbs are typically dimmers
        ],
        IndigoDeviceType.RELAY: [
            r".*[Rr]elay.*",
            r".*[Ss]witch.*",
            r".*[Pp]lug.*",
            r".*[Oo]utlet.*",
        ],
        IndigoDeviceType.SENSOR: [
            r".*[Ss]ensor.*",
            r".*[Dd]etector.*",
            r".*[Mm]otion.*",
            r".*[Tt]emperature.*",
            r".*[Hh]umidity.*",
        ],
        IndigoDeviceType.THERMOSTAT: [
            r".*[Tt]hermostat.*",
            r".*[Hh]vac.*",
            r".*[Cc]limate.*",
        ],
        IndigoDeviceType.SPEEDCONTROL: [
            r".*[Ff]an.*",
            r".*[Ss]peed.*",
        ],
        IndigoDeviceType.SPRINKLER: [
            r".*[Ss]prinkler.*",
            r".*[Ii]rrigation.*",
            r".*[Ww]ater.*",
        ],
    }
    
    @classmethod
    def classify_device(cls, device: Dict[str, Any]) -> str:
        """
        Classify a device based on its class and deviceTypeId.
        
        Args:
            device: Device dictionary with 'class' and 'deviceTypeId' fields
            
        Returns:
            Device type string (from IndigoDeviceType enum)
        """
        # First, try classification by device class
        device_class = device.get("class", "")
        if device_class in cls.CLASS_TO_TYPE_MAP:
            return cls.CLASS_TO_TYPE_MAP[device_class].value
        
        # If class-based classification fails, try deviceTypeId patterns
        device_type_id = device.get("deviceTypeId", "")
        if device_type_id:
            for device_type, patterns in cls.DEVICETYPE_PATTERNS.items():
                for pattern in patterns:
                    if re.match(pattern, device_type_id, re.IGNORECASE):
                        return device_type.value
        
        # Default to base device type
        return IndigoDeviceType.DEVICE.value
    
    @classmethod
    def filter_devices_by_type(cls, devices: List[Dict[str, Any]], device_type: str) -> List[Dict[str, Any]]:
        """
        Filter a list of devices by logical device type.
        
        Args:
            devices: List of device dictionaries
            device_type: Device type to filter by (from IndigoDeviceType enum)
            
        Returns:
            List of devices matching the specified type
        """
        if not IndigoDeviceType.is_valid_type(device_type):
            return []
        
        filtered_devices = []
        for device in devices:
            classified_type = cls.classify_device(device)
            if classified_type == device_type:
                filtered_devices.append(device)
        
        return filtered_devices
    
    @classmethod
    def get_device_type_distribution(cls, devices: List[Dict[str, Any]]) -> Dict[str, int]:
        """
        Get distribution of device types in a list of devices.
        
        Args:
            devices: List of device dictionaries
            
        Returns:
            Dictionary mapping device types to counts
        """
        distribution = {}
        for device in devices:
            device_type = cls.classify_device(device)
            distribution[device_type] = distribution.get(device_type, 0) + 1
        
        return distribution