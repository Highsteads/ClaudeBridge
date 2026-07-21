"""
Custom JSON encoder for handling Indigo entity serialization.
"""

import json
from datetime import datetime, date
from typing import Any, Dict, List, Union

# Keys to keep for slim device representation (fast search results)
KEYS_TO_KEEP_MINIMAL_DEVICES = [
    "id",
    "name",
    "class",
    "deviceTypeId",
    "description",
    "model",
    "protocol",
    "pluginId",
    "address",
    "resolvedAddress",
    "enabled",
    "onState",
    "brightness",
    "brightnessLevel",
    "lastChanged",
    "states",
]


class IndigoJSONEncoder(json.JSONEncoder):
    """JSON encoder that handles datetime objects and other non-serializable types."""
    
    def default(self, obj: Any) -> Any:
        """
        Convert non-serializable objects to serializable format.
        
        Args:
            obj: Object to serialize
            
        Returns:
            Serializable representation of the object
        """
        if isinstance(obj, (datetime, date)):
            return obj.isoformat()
        elif isinstance(obj, bytes):
            # Handle bytes by decoding to string. Use errors='replace' so
            # non-UTF-8 bytes leave a U+FFFD marker rather than being silently
            # dropped.
            return obj.decode('utf-8', errors='replace')
        elif hasattr(obj, '__dict__'):
            # Handle custom objects by converting to dict, but exclude
            # underscore-prefixed (private) attributes so internal/credential
            # references aren't accidentally serialised into a tool response.
            return {k: v for k, v in obj.__dict__.items() if not k.startswith('_')}
        
        # Let the base class raise TypeError for unsupported types
        return super().default(obj)


def safe_json_dumps(data: Any, indent: int = 2) -> str:
    """
    Safely serialize data to JSON string using custom encoder.
    
    Args:
        data: Data to serialize
        indent: JSON indentation level
        
    Returns:
        JSON string representation
    """
    return json.dumps(data, cls=IndigoJSONEncoder, indent=indent)


def filter_json(json_obj: Union[Dict, List], keys_to_keep: List[str]) -> Union[Dict, List]:
    """
    Extracts specified properties from each object in a JSON object and returns them as a dictionary.

    Args:
        json_obj (Dict or List): The object containing an array of json objects to be filtered.
        keys_to_keep (list): A list of property names to extract from each object.

    Returns:
        return: A filtered array of JSON objects containing only the specified keys.
    """

    if not isinstance(keys_to_keep, list):
        raise ValueError("Keys to keep must be provided as a list.")

    if isinstance(json_obj, dict):
        # Keep whitelisted top-level keys and copy their values VERBATIM.
        # Do NOT recurse into a kept sub-object with the same keep-list: a
        # device's `states` dict (temperature, humidity, …) has keys that are
        # legitimately absent from the top-level keep-list, so recursing would
        # silently strip every reading and hand the model a stateless device.
        # This matches the list branch below, which already copies dict items
        # verbatim.
        return {key: json_obj[key] for key in keys_to_keep if key in json_obj}
    elif isinstance(json_obj, list):
        # Recursively process each element in the list
        result = []
        for item in json_obj:
            if isinstance(item, dict):
                # For dict items, keep only the specified keys that exist
                filtered_item = {key: item[key] for key in keys_to_keep if key in item}
                if filtered_item:  # Only add if we have at least one key
                    result.append(filtered_item)
            elif isinstance(item, list):
                filtered_item = filter_json(item, keys_to_keep)
                result.append(filtered_item)
        return result
    else:
        # If it's not a dict or list, return as-is (should not occur at the top level)
        raise ValueError(
            "Input must be a dictionary, a list of dictionaries, or a nested structure."
        )