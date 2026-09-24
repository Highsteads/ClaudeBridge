"""
Shared handlers for listing Indigo entities.
Used by both MCP tools and resources for consistent behavior.
"""

import logging
from typing import Dict, List, Any, Optional

from typing import TYPE_CHECKING

if TYPE_CHECKING:   # type hint only — importing it here would be circular
    from ..adapters.indigo_data_provider import IndigoDataProvider
from ..common.state_filter import StateFilter
from ..common.indigo_device_types import DeviceClassifier
from ..tools.base_handler import BaseToolHandler


class ListHandlers(BaseToolHandler):
    """Shared handlers for listing entities."""
    
    def __init__(
        self, 
        data_provider: "IndigoDataProvider",
        logger: Optional[logging.Logger] = None
    ):
        """
        Initialize the list handlers.
        
        Args:
            data_provider: Data provider for accessing entity data
            logger: Optional logger instance
        """
        super().__init__(tool_name="list_handlers", logger=logger)
        self.data_provider = data_provider
    
    def list_all_devices(
        self, 
        state_filter: Optional[Dict[str, Any]] = None,
        device_types: Optional[List[str]] = None
    ) -> List[Dict[str, Any]]:
        """
        Get all devices, optionally filtered by state and/or type.
        
        Args:
            state_filter: Optional state conditions to filter by
            device_types: Optional list of device types to filter by
            
        Returns:
            List of device dictionaries
        """
        try:
            # Get all devices
            devices = self.data_provider.get_all_devices()
            
            # Apply device type filtering if specified
            if device_types:
                filtered_devices = []
                device_type_set = set(device_types)
                
                for device in devices:
                    classified_type = DeviceClassifier.classify_device(device)
                    if classified_type in device_type_set:
                        filtered_devices.append(device)
                
                devices = filtered_devices
            
            # Apply state filtering if specified
            if state_filter:
                devices = StateFilter.filter_by_state(devices, state_filter)
                self.debug_log(f"Filtered to {len(devices)} devices by state conditions: {state_filter}")
            
            # Create query info for logging
            query_info = {}
            if state_filter:
                query_info["state_filter"] = state_filter
            if device_types:
                query_info["device_types"] = device_types
            
            self.log_tool_outcome("list_devices", True, count=len(devices), query_info=query_info)
            return devices
            
        except Exception as e:
            self.error_log(f"Error listing devices: {e}")
            raise
    
    def list_all_variables(self) -> List[Dict[str, Any]]:
        """
        Get all variables.
        
        Returns:
            List of variable dictionaries
        """
        try:
            variables = self.data_provider.get_all_variables()
            self.log_tool_outcome("list_variables", True, count=len(variables), query_info={})
            return variables
            
        except Exception as e:
            self.error_log(f"Error listing variables: {e}")
            raise
    
    def list_all_action_groups(self) -> List[Dict[str, Any]]:
        """
        Get all action groups.
        
        Returns:
            List of action group dictionaries
        """
        try:
            actions = self.data_provider.get_all_actions()
            self.log_tool_outcome("list_action_groups", True, count=len(actions), query_info={})
            return actions
            
        except Exception as e:
            self.error_log(f"Error listing action groups: {e}")
            raise
    
    def get_devices_by_state(
        self,
        state_conditions: Dict[str, Any],
        device_types: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        """
        Get devices matching specific state conditions.
        
        Args:
            state_conditions: State requirements using Indigo state names
            device_types: Optional list of device types to filter
            
        Returns:
            Dictionary with matching devices and summary
        """
        try:
            # Use full (unfiltered) device data so state properties are available for matching
            all_devices = self.data_provider.get_all_devices_unfiltered()

            # Apply device type filtering if specified
            if device_types:
                type_set = set(device_types)
                from ..common.indigo_device_types import DeviceClassifier
                all_devices = [d for d in all_devices if DeviceClassifier.classify_device(d) in type_set]

            # Filter by state using full data
            from ..common.state_filter import StateFilter
            devices = StateFilter.filter_by_state(all_devices, state_conditions)

            # Return slim fields in results
            from ..common.json_encoder import filter_json, KEYS_TO_KEEP_MINIMAL_DEVICES
            devices = filter_json(devices, KEYS_TO_KEEP_MINIMAL_DEVICES)
            
            # Create summary
            summary = f"Found {len(devices)} devices matching state conditions"
            if device_types:
                summary += f" (types: {', '.join(device_types)})"
            
            return {
                "devices": devices,
                "count": len(devices),
                "state_conditions": state_conditions,
                "device_types": device_types,
                "summary": summary
            }
            
        except Exception as e:
            self.logger.error(f"Error getting devices by state: {e}")
            raise

    def resolve_device_folder(self, folder: Any):
        """A device folder given by id or name -> (folder_id, None) or (None, error).

        A name matches exactly first, then ignoring case. An unknown folder is
        an error naming the folders that do exist, never an empty list — an
        empty list would read as "that folder holds no devices".
        """
        folders = self.data_provider.get_device_folders()
        text = str(folder).strip()
        if text.lstrip("-").isdigit():
            wanted = int(text)
            if wanted == 0 or any(f["id"] == wanted for f in folders):
                return wanted, None
        else:
            for same in (lambda f: f["name"] == text,
                         lambda f: f["name"].lower() == text.lower()):
                hits = [f for f in folders if same(f)]
                if len(hits) == 1:
                    return hits[0]["id"], None
                if len(hits) > 1:
                    return None, (f"{len(hits)} device folders are called '{text}'; "
                                  f"use the folder id: {[f['id'] for f in hits]}")
        names = sorted(f["name"] for f in folders)
        return None, f"No device folder '{text}'. Device folders: {names}"

    @staticmethod
    def project_fields(devices: List[Dict[str, Any]], fields: List[str]):
        """Cut each device down to id, name and the named fields.

        A field is a top-level device property (address, pluginId, folderId,
        lastChanged...) or, failing that, a state name. A field no device has
        is reported rather than silently left out, so a misspelt state name is
        visible instead of reading as "every device lacks this".
        """
        rows, seen = [], set()
        for dev in devices:
            row = {"id": dev.get("id"), "name": dev.get("name")}
            states = dev.get("states") or {}
            for field in fields:
                if field in dev:
                    row[field] = dev[field]
                    seen.add(field)
                elif field in states:
                    row[field] = states[field]
                    seen.add(field)
            rows.append(row)
        return rows, [f for f in fields if f not in seen]

    def list_devices_filtered(
        self,
        device_types: Optional[List[str]] = None,
        state_filter: Optional[Dict[str, Any]] = None,
        plugin_id: Optional[str] = None,
        folder_id: Optional[int] = None,
        fields: Optional[List[str]] = None,
        limit: int = 200,
    ) -> Dict[str, Any]:
        """Devices narrowed by any mix of type, owning plugin, folder and
        state, sorted by name, as slim rows or just the fields asked for."""
        devices = self.data_provider.get_all_devices_unfiltered()
        if device_types:
            type_set = set(device_types)
            devices = [d for d in devices if DeviceClassifier.classify_device(d) in type_set]
        if plugin_id is not None:
            devices = [d for d in devices if (d.get("pluginId") or "") == plugin_id]
        if folder_id is not None:
            devices = [d for d in devices if d.get("folderId") == folder_id]
        if state_filter:
            devices = StateFilter.filter_by_state(devices, state_filter)
        devices.sort(key=lambda d: str(d.get("name", "")).lower())

        total = len(devices)
        devices = devices[:limit]
        result: Dict[str, Any] = {}
        if fields:
            rows, missing = self.project_fields(devices, fields)
            result["devices"] = rows
            if missing:
                result["fields_not_found"] = missing
                result["note"] = ("No listed device has these as a property or a state. "
                                  "State names are case-sensitive (brightnessLevel, not "
                                  "brightnesslevel).")
        else:
            from ..common.json_encoder import filter_json, KEYS_TO_KEEP_MINIMAL_DEVICES
            result["devices"] = filter_json(devices, KEYS_TO_KEEP_MINIMAL_DEVICES)
        result.update(count=len(result["devices"]), total_matched=total,
                      truncated=total > limit, limit=limit)
        return result

    def list_variable_folders(self) -> Dict[str, Any]:
        """
        Get all variable folders.

        Returns:
            Dictionary with folder list and count
        """
        try:
            # Get all variable folders
            folders = self.data_provider.get_variable_folders()

            # Create summary
            summary = f"Found {len(folders)} variable folders"

            return {
                "folders": folders,
                "count": len(folders),
                "summary": summary
            }

        except Exception as e:
            self.logger.error(f"Error listing variable folders: {e}")
            raise