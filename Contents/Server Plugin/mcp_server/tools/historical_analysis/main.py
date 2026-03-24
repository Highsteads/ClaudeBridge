"""
Main handler for historical data analysis.
"""

import logging
import os
import time
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional, Tuple
from zoneinfo import ZoneInfo

from ...adapters.data_provider import DataProvider
from ..base_handler import BaseToolHandler
from ...common.influxdb import InfluxDBClient, InfluxDBQueryBuilder
from ...common.openai_client.main import _get_client


# Alternative fields to try for device properties
_ALTERNATIVE_FIELDS = [
    "onState", "onOffState", "isPoweredOn",
    "brightness", "brightnessLevel",
    "temperature", "temperatureInput1", 
    "humidity", "humidityInput1",
    "sensorValue", "energyAccumTotal", "state"
]


class HistoricalAnalysisHandler(BaseToolHandler):
    """Handler for historical data analysis using direct InfluxDB queries."""
    
    def __init__(
        self,
        data_provider: DataProvider,
        logger: Optional[logging.Logger] = None
    ):
        """
        Initialize the historical analysis handler.
        
        Args:
            data_provider: Data provider for accessing entity data
            logger: Optional logger instance
        """
        super().__init__(tool_name="historical_analysis", logger=logger)
        self.data_provider = data_provider
    
    def analyze_historical_data(
        self,
        query: str,
        entity_names: List[str],
        time_range_days: int = 30,
        entity_type: str = "auto"
    ) -> Dict[str, Any]:
        """
        Analyze historical data for the specified devices and/or variables.
        
        Args:
            query: User's natural language query about the data
            entity_names: List of device or variable names to analyze
            time_range_days: Number of days to analyze (default: 30)
            entity_type: Type of entities to analyze ("auto", "devices", "variables", "mixed")
            
        Returns:
            Dictionary with analysis results
        """
        start_time = time.time()
        
        try:
            self.info_log(f"Starting historical analysis for {len(entity_names)} entities over {time_range_days} days")
            self.debug_log(f"Query: '{query}'")
            self.debug_log(f"Entities: {entity_names}")
            self.debug_log(f"Entity type: {entity_type}")
            
            # Validate inputs
            validation_error = self.validate_required_params(
                {"query": query, "entity_names": entity_names},
                ["query", "entity_names"]
            )
            if validation_error:
                return validation_error
            
            if not entity_names:
                return self.handle_exception(
                    ValueError("No entity names provided"),
                    "validating input parameters"
                )
            
            if time_range_days <= 0 or time_range_days > 365:
                return self.handle_exception(
                    ValueError("Time range must be between 1 and 365 days"),
                    "validating time range"
                )
            
            # Validate entity names exist and determine types
            validation_result = self._validate_entity_names(entity_names, entity_type)
            if not validation_result["all_valid"]:
                return {
                    "success": False,
                    "error": validation_result["error_message"],
                    "tool": self.tool_name,
                    "report": validation_result["detailed_report"],
                    "valid_entities": validation_result["valid_entities"],
                    "invalid_entities": validation_result["invalid_entities"],
                    "suggestions": validation_result["suggestions"],
                    "analysis_duration_seconds": time.time() - start_time
                }
            
            # Check if InfluxDB is available
            if os.environ.get("INFLUXDB_ENABLED", "false").lower() != "true":
                self.warning_log("InfluxDB is not enabled - historical analysis not available")
                return {
                    "success": False,
                    "error": "InfluxDB is not enabled. Please enable InfluxDB in plugin configuration to use historical analysis.",
                    "tool": self.tool_name,
                    "report": "Historical analysis requires InfluxDB to be enabled and configured.",
                    "summary_stats": {},
                    "devices_analyzed": []
                }
            
            # Determine entity types and separate them
            entity_classification = validation_result["entity_classification"]
            devices = entity_classification.get("devices", [])
            variables = entity_classification.get("variables", [])
            
            # Get historical data for all entities
            all_results = []
            entities_analyzed = []
            
            # Process devices
            for device_name in devices:
                self.debug_log(f"Querying historical data for device: {device_name}")
                
                # Use LLM to intelligently select device properties based on query
                device_results = []
                recommended_properties = self._get_recommended_properties(device_name, query)
                
                if recommended_properties:
                    self.info_log(f"LLM recommended properties for {device_name}: {recommended_properties}")
                    
                    # Try recommended properties in order
                    for device_property in recommended_properties:
                        try:
                            self.debug_log(f"Querying InfluxDB for {device_name}.{device_property}")
                            property_results = self._get_historical_device_data(
                                device_name, device_property, time_range_days
                            )
                            if property_results:
                                device_results.extend(property_results)
                                self.info_log(f"✅ Found {len(property_results)} records for {device_name}.{device_property}")
                                break  # Found data, stop trying other properties
                            else:
                                self.debug_log(f"❌ No data for {device_name}.{device_property}")
                        except Exception as e:
                            self.debug_log(f"❌ Error querying {device_name}.{device_property}: {e}")
                            continue
                
                # Fallback to predefined fields if LLM recommendations didn't work
                if not device_results:
                    self.debug_log(f"LLM recommendations failed, falling back to predefined properties: {_ALTERNATIVE_FIELDS}")
                    for device_property in _ALTERNATIVE_FIELDS:
                        try:
                            self.debug_log(f"Trying fallback property: {device_name}.{device_property}")
                            property_results = self._get_historical_device_data(
                                device_name, device_property, time_range_days
                            )
                            if property_results:
                                device_results.extend(property_results)
                                self.info_log(f"✅ Fallback success: Found {len(property_results)} records for {device_name}.{device_property}")
                                break  # Found data, stop trying other properties
                            else:
                                self.debug_log(f"❌ No fallback data for {device_name}.{device_property}")
                        except Exception as e:
                            self.debug_log(f"❌ Fallback error for {device_name}.{device_property}: {e}")
                            continue
                
                if device_results:
                    all_results.extend(device_results)
                    entities_analyzed.append(device_name)
            
            # Process variables (simpler - only 'value' field)
            for variable_name in variables:
                self.debug_log(f"Querying historical data for variable: {variable_name}")
                
                try:
                    variable_results = self._get_historical_variable_data(
                        variable_name, time_range_days
                    )
                    if variable_results:
                        all_results.extend(variable_results)
                        entities_analyzed.append(variable_name)
                        self.info_log(f"✅ Found {len(variable_results)} records for variable {variable_name}")
                    else:
                        self.debug_log(f"❌ No data for variable {variable_name}")
                except Exception as e:
                    self.debug_log(f"❌ Error querying variable {variable_name}: {e}")
                    continue
            
            # Calculate analysis duration
            analysis_duration = time.time() - start_time
            
            # Create enhanced summary statistics
            summary_stats = self._calculate_summary_statistics(
                all_results, entities_analyzed, time_range_days, analysis_duration
            )
            
            # Format report with better organization
            if all_results:
                report = self._format_analysis_report(
                    all_results, entities_analyzed, time_range_days, summary_stats, entity_classification
                )
                
                self.info_log(f"Analysis completed successfully in {analysis_duration:.2f}s")
                return self.create_success_response(
                    data={
                        "report": report,
                        "summary_stats": summary_stats,
                        "entities_analyzed": entities_analyzed,
                        "total_data_points": len(all_results),
                        "time_range_days": time_range_days,
                        "analysis_duration_seconds": analysis_duration,
                        "entity_classification": entity_classification
                    },
                    message=f"Analyzed {len(all_results)} changes from {len(entities_analyzed)} entities ({len(devices)} devices, {len(variables)} variables)"
                )
            else:
                self.warning_log("No historical data found for any devices")
                return {
                    "success": False,
                    "error": "No historical data found for the specified devices",
                    "tool": self.tool_name,
                    "report": "No historical data was found for any of the specified devices in the given time range.",
                    "summary_stats": summary_stats,
                    "devices_analyzed": [],
                    "analysis_duration_seconds": analysis_duration
                }
            
        except Exception as e:
            analysis_duration = time.time() - start_time
            return self.handle_exception(e, f"analyzing historical data (duration: {analysis_duration:.2f}s)")
    
    def _get_historical_device_data(
        self, device_name: str, device_property: str, time_range_days: int = 60
    ) -> List[str]:
        """
        Query InfluxDB for historical device data and return formatted results.
        
        Args:
            device_name: The device name to query data for
            device_property: The device property to query data for
            time_range_days: Number of days to look back for historical data
            
        Returns:
            List of formatted messages describing device state changes
        """
        try:
            client = InfluxDBClient(logger=self.logger)
            query_builder = InfluxDBQueryBuilder(logger=self.logger)
            
            if not client.is_enabled() or not client.test_connection():
                return []
            
            # Build and execute query
            query = query_builder.build_device_history_query(
                device_name=device_name,
                device_property=device_property,
                time_range_days=time_range_days
            )
            
            results = client.execute_query(query)
            if not results:
                self.debug_log(f"InfluxDB query returned no results for {device_name}.{device_property}")
                return []
            
            self.debug_log(f"InfluxDB returned {len(results)} raw records for {device_name}.{device_property}")
            
            # Convert to formatted state change messages
            formatted_results = []
            saved_state = None
            from_timestamp = None
            
            for data_record in results:
                record_time_str = data_record.get("time")
                if not record_time_str:
                    continue
                
                timestamp_local = self._convert_to_local_timezone(record_time_str)
                field_value = data_record.get(device_property)
                
                if saved_state is None:
                    from_timestamp = timestamp_local
                    saved_state = field_value
                elif saved_state != field_value and from_timestamp is not None:
                    # Format duration in a more readable way
                    duration_str = self._format_duration(
                        from_timestamp, timestamp_local
                    )
                    
                    # Format timestamps with timezone info
                    from_str = from_timestamp.strftime("%Y-%m-%d %H:%M:%S %Z")
                    to_str = timestamp_local.strftime("%Y-%m-%d %H:%M:%S %Z")
                    
                    # Format the state value with context
                    state_str = self._format_state_value(saved_state, device_property)
                    
                    message = (
                        f"{device_name}.{device_property} was {state_str} for {duration_str}, "
                        f"from {from_str} to {to_str}"
                    )
                    formatted_results.append(message)
                    self.debug_log(message)
                    from_timestamp = timestamp_local
                    saved_state = field_value
            
            # Handle final state (ongoing until now)
            to_timestamp = datetime.now().astimezone()
            if from_timestamp is not None and saved_state is not None:
                # Format duration in a more readable way
                duration_str = self._format_duration(
                    from_timestamp, to_timestamp
                )
                
                # Format timestamps with timezone info
                from_str = from_timestamp.strftime("%Y-%m-%d %H:%M:%S %Z")
                to_str = to_timestamp.strftime("%Y-%m-%d %H:%M:%S %Z")
                
                # Format the state value with context
                final_state = self._format_state_value(saved_state, device_property)
                
                message = (
                    f"{device_name}.{device_property} is currently {final_state} (for {duration_str}), "
                    f"since {from_str}"
                )
                formatted_results.append(message)
            
            return formatted_results
            
        except Exception as e:
            self.debug_log(f"Error querying {device_name}.{device_property}: {e}")
            return []
    
    def _get_delta_summary(self, start_time: datetime, end_time: datetime) -> Tuple[int, int, int]:
        """
        Calculate the difference between two datetime objects.
        
        Args:
            start_time: The start time
            end_time: The end time
            
        Returns:
            Tuple of hours, minutes, and seconds of the time difference
        """
        delta = end_time - start_time
        
        # Handle negative deltas
        if delta.total_seconds() < 0:
            self.warning_log(f"Negative time delta detected: {start_time} to {end_time}")
            return 0, 0, 0
        
        total_seconds = int(delta.total_seconds())
        hours = total_seconds // 3600
        minutes = (total_seconds % 3600) // 60
        seconds = total_seconds % 60
        return hours, minutes, seconds
    
    def _format_duration(self, start_time: datetime, end_time: datetime) -> str:
        """
        Format duration between two times in a human-readable way.
        
        Args:
            start_time: The start time
            end_time: The end time
            
        Returns:
            Formatted duration string
        """
        hours, minutes, seconds = self._get_delta_summary(start_time, end_time)
        
        # Build duration parts
        parts = []
        
        # For long durations, show days
        if hours >= 24:
            days = hours // 24
            remaining_hours = hours % 24
            if days == 1:
                parts.append("1 day")
            else:
                parts.append(f"{days} days")
            if remaining_hours > 0:
                if remaining_hours == 1:
                    parts.append("1 hour")
                else:
                    parts.append(f"{remaining_hours} hours")
        elif hours > 0:
            if hours == 1:
                parts.append("1 hour")
            else:
                parts.append(f"{hours} hours")
        
        # Add minutes for durations less than 24 hours
        if hours < 24 and minutes > 0:
            if minutes == 1:
                parts.append("1 minute")
            else:
                parts.append(f"{minutes} minutes")
        
        # Add seconds for very short durations
        if hours == 0 and minutes < 5:
            if seconds == 1:
                parts.append("1 second")
            else:
                parts.append(f"{seconds} seconds")
        
        # Handle empty duration
        if not parts:
            return "less than a second"
        
        # Format the output
        if len(parts) == 1:
            return parts[0]
        elif len(parts) == 2:
            return f"{parts[0]} and {parts[1]}"
        else:
            return f"{', '.join(parts[:-1])}, and {parts[-1]}"
    
    def _convert_to_local_timezone(self, datetime_str: str) -> datetime:
        """
        Convert an ISO formatted UTC datetime string to a local timezone-aware datetime object.
        
        Args:
            datetime_str: Datetime string in ISO format (ending with 'Z')
            
        Returns:
            Local timezone-aware datetime object
        """
        try:
            # Handle both 'Z' suffix and without
            if datetime_str.endswith('Z'):
                datetime_str = datetime_str.rstrip('Z')
            
            # Parse the datetime and set UTC timezone
            utc_datetime = datetime.fromisoformat(datetime_str).replace(tzinfo=ZoneInfo("UTC"))
            
            # Convert to local timezone
            local_datetime = utc_datetime.astimezone()
            
            return local_datetime
        except Exception as e:
            self.error_log(f"Failed to parse datetime '{datetime_str}': {e}")
            # Return current time as fallback
            return datetime.now().astimezone()
    
    def _format_state_value(self, value, property_name: str = None) -> str:
        """
        Format state value for display with context-aware formatting.
        
        Args:
            value: Raw state value
            property_name: Name of the property for context-aware formatting
            
        Returns:
            Formatted state string
        """
        if value is None:
            return "unknown"
        
        # Boolean values
        if isinstance(value, bool):
            return "on" if value else "off"
        
        # Numeric values with context-aware formatting
        if isinstance(value, (int, float)):
            # Power values (check before on/off states to avoid conflict)
            if property_name and any(term in property_name.lower() for term in ['realpower', 'power']) and 'onstate' not in property_name.lower():
                if value >= 1000:
                    return f"{value/1000:.2f} kW"
                else:
                    return f"{value:.1f} W"
            
            # Energy values
            elif property_name and 'energy' in property_name.lower():
                if value >= 1000:
                    return f"{value/1000:.2f} kWh"
                else:
                    return f"{value:.2f} Wh"
            
            # Temperature values
            elif property_name and 'temp' in property_name.lower():
                return f"{value:.1f}°"
            
            # Humidity values
            elif property_name and 'humid' in property_name.lower():
                return f"{value:.1f}%"
            
            # Brightness/dimming values
            elif property_name and any(term in property_name.lower() for term in ['bright', 'dim', 'level']):
                if 0 <= value <= 1:
                    return f"{value * 100:.0f}%"
                elif 0 <= value <= 100:
                    return f"{value:.0f}%"
                else:
                    return f"{value:.1f}"
            
            # Battery level
            elif property_name and 'battery' in property_name.lower():
                return f"{value:.0f}%"
            
            # On/Off states (check after other specific types)
            elif property_name and any(term in property_name.lower() for term in ['onstate', 'onoff']):
                if value in [0, 0.0]:
                    return "off"
                elif value in [1, 1.0]:
                    return "on"
                else:
                    return f"{value:.0f}"  # For intermediate states
            
            # Generic numeric formatting
            else:
                # Use appropriate decimal places based on value
                if value == int(value):
                    return f"{int(value)}"
                elif abs(value) < 10:
                    return f"{value:.2f}"
                elif abs(value) < 100:
                    return f"{value:.1f}"
                else:
                    return f"{value:.0f}"
        
        # String values
        else:
            value_str = str(value).strip()
            # Clean up common string values
            if value_str.lower() in ['true', 'on', '1']:
                return "on"
            elif value_str.lower() in ['false', 'off', '0']:
                return "off"
            else:
                return value_str
    
    def get_available_devices(self) -> List[str]:
        """
        Get list of available devices for analysis.
        
        Returns:
            List of device names
        """
        try:
            # Get devices from data provider
            devices = self.data_provider.get_all_devices()
            device_names = [device.get("name", "") for device in devices if device.get("name")]
            
            self.debug_log(f"Found {len(device_names)} available devices")
            return device_names
            
        except Exception as e:
            self.error_log(f"Failed to get available devices: {e}")
            return []
    
    def is_influxdb_available(self) -> bool:
        """
        Check if InfluxDB is available for historical analysis.
        
        Returns:
            True if InfluxDB is enabled and configured
        """
        try:
            if os.environ.get("INFLUXDB_ENABLED", "false").lower() != "true":
                return False
            
            client = InfluxDBClient(logger=self.logger)
            return client.test_connection()
            
        except Exception as e:
            self.debug_log(f"InfluxDB availability check failed: {e}")
            return False
    
    def _get_device_properties(self, device_name: str) -> List[str]:
        """
        Get all available properties for a device.
        
        Args:
            device_name: Name of the device
            
        Returns:
            List of property names for the device
        """
        try:
            # Get device from data provider
            devices = self.data_provider.get_all_devices()
            target_device = None
            
            for device in devices:
                if device.get("name") == device_name:
                    target_device = device
                    break
            
            if not target_device:
                self.debug_log(f"Device '{device_name}' not found")
                return _ALTERNATIVE_FIELDS  # Fallback to predefined fields
            
            # Extract all properties that have values (excluding system/meta properties)
            properties = []
            excluded_props = {
                'id', 'name', 'deviceTypeId', 'pluginId', 'pluginProps', 
                'sharedProps', 'globalProps', 'errorState', 'configured',
                'enabled', 'version', 'protocol', 'address', 'description',
                'model', 'remoteDisplay', 'allowSensorValueChange',
                'allowOnStateChange', 'supportsStatusRequest', 'buttonGroupCount',
                'supportsAllOff', 'supportsAllLightsOnOff', 'folderId', 'subModel',
                'subType', 'lastChanged', 'lastSuccessfulComm', 'ownerProps',
                'energyAccumBaseTime', 'energyAccumTimeDelta'
            }
            
            # First, extract properties from states dictionary (highest priority for historical analysis)
            states_dict = target_device.get('states', {})
            if isinstance(states_dict, dict):
                self.debug_log(f"Found states dictionary with {len(states_dict)} entries")
                for state_key, state_value in states_dict.items():
                    # Skip nested state properties (like state.on, state.off)
                    if '.' not in state_key and self._is_valid_property_value(state_value):
                        properties.append(state_key)
                        self.debug_log(f"Added state property: {state_key} = {state_value}")
            
            # Then, extract top-level properties (lower priority)
            for key, value in target_device.items():
                # Include properties that are likely state/sensor values
                if (key not in excluded_props and 
                    key != 'states' and  # Skip states dict itself
                    value is not None and 
                    not key.startswith('_') and
                    self._is_valid_property_value(value)):
                    # Only add if not already found in states
                    if key not in properties:
                        properties.append(key)
            
            self.debug_log(f"Found {len(properties)} properties for {device_name}: {properties}")
            
            # Always include common fallback properties if not already present
            for prop in _ALTERNATIVE_FIELDS:
                if prop not in properties:
                    properties.append(prop)
            
            return properties
            
        except Exception as e:
            self.debug_log(f"Error getting properties for {device_name}: {e}")
            return _ALTERNATIVE_FIELDS  # Fallback to predefined fields
    
    def _get_recommended_properties(self, device_name: str, user_query: str) -> List[str]:
        """
        Use LLM to recommend device properties to analyze based on user query.
        
        Args:
            device_name: Name of the device
            user_query: User's analysis query
            
        Returns:
            List of 1-3 recommended property names, ordered by relevance
        """
        try:
            # Get all available properties for the device
            available_properties = self._get_device_properties(device_name)
            
            if not available_properties:
                self.debug_log(f"No properties found for device '{device_name}'")
                return []
            
            # Create LLM prompt
            properties_str = ", ".join(available_properties)
            
            system_prompt = """You are an expert in Indigo home automation system analysis. 
Given a user's query about analyzing historical data for a device, recommend the most relevant device properties to query.

Rules:
- Return 1-3 property names that best match the user's query
- Return properties in order of relevance (most relevant first)  
- Only return properties from the provided list
- Properties may come from device states or top-level properties
- For presence/occupancy queries, prioritize: onOffState, displayState, state, pending, presence
- For general queries about "state changes" or "activity", prioritize: onState, onOffState, displayState, state
- For brightness/dimming queries, prioritize: brightness, brightnessLevel  
- For temperature queries, prioritize: temperature, temperatureInput1
- For humidity queries, prioritize: humidity, humidityInput1
- For sensor queries, prioritize: sensorValue, state, displayState
- For energy/power queries, prioritize: energyAccumTotal, realPower, accumEnergyTotal
- For timer/persistence devices, prioritize: onOffState, displayState, state, pending

Return only the property names, separated by commas, no explanations."""

            user_prompt = f"""Device: {device_name}
Available properties: {properties_str}
User query: "{user_query}"

Recommend 1-3 most relevant properties:"""

            # Get OpenAI client
            try:
                client = _get_client()
            except Exception as e:
                self.debug_log(f"OpenAI client not available: {e}, using fallback properties")
                return _ALTERNATIVE_FIELDS[:3]
            
            # Make LLM call
            response = client.chat.completions.create(
                model="gpt-4",
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                temperature=0.1,
                max_tokens=50
            )
            
            # Parse response
            recommendations = response.choices[0].message.content.strip()
            recommended_properties = [prop.strip() for prop in recommendations.split(",")]
            
            # Validate recommendations are in available properties
            valid_properties = []
            for prop in recommended_properties:
                if prop in available_properties:
                    valid_properties.append(prop)
            
            if valid_properties:
                self.debug_log(f"LLM recommended {len(valid_properties)} properties for '{user_query}': {valid_properties}")
                return valid_properties[:3]  # Max 3 properties
            else:
                self.debug_log("LLM recommendations were not valid, using fallback")
                return _ALTERNATIVE_FIELDS[:3]
                
        except Exception as e:
            self.debug_log(f"Error getting LLM recommendations for {device_name}: {e}")
            return _ALTERNATIVE_FIELDS[:3]  # Fallback to first 3 predefined fields
    
    def _validate_device_names(self, device_names: List[str]) -> Dict[str, Any]:
        """
        Validate that all device names exist in the Indigo system.
        
        Args:
            device_names: List of device names to validate
            
        Returns:
            Dictionary with validation results and suggestions
        """
        try:
            # Get all available devices
            all_devices = self.data_provider.get_all_devices()
            existing_device_names = {device.get("name", "") for device in all_devices if device.get("name")}
            
            valid_devices = []
            invalid_devices = []
            suggestions = []
            
            # Check each device name
            for device_name in device_names:
                if device_name in existing_device_names:
                    valid_devices.append(device_name)
                else:
                    invalid_devices.append(device_name)
                    
                    # Find similar device names for suggestions
                    similar_names = self._find_similar_device_names(device_name, existing_device_names)
                    if similar_names:
                        suggestions.append({
                            "invalid_name": device_name,
                            "suggestions": similar_names[:3]  # Top 3 suggestions
                        })
            
            all_valid = len(invalid_devices) == 0
            
            if all_valid:
                return {
                    "all_valid": True,
                    "valid_devices": valid_devices,
                    "invalid_devices": [],
                    "suggestions": [],
                    "error_message": "",
                    "detailed_report": ""
                }
            else:
                # Create detailed error report
                error_lines = [f"Device validation failed. {len(invalid_devices)} of {len(device_names)} devices not found:"]
                
                for invalid_device in invalid_devices:
                    error_lines.append(f"  ❌ '{invalid_device}' - NOT FOUND")
                    
                    # Add suggestions if available
                    device_suggestions = next(
                        (item["suggestions"] for item in suggestions if item["invalid_name"] == invalid_device),
                        []
                    )
                    if device_suggestions:
                        error_lines.append(f"     💡 Did you mean: {', '.join(device_suggestions)}")
                
                if valid_devices:
                    error_lines.append(f"\n✅ Valid devices found: {', '.join(valid_devices)}")
                
                error_lines.extend([
                    "\n📋 To find correct device names, use:",
                    "  • search_entities('your device description')",
                    "  • list_devices() to see all devices",
                    "  • get_devices_by_type('device_type') for specific types"
                ])
                
                detailed_report = "\n".join(error_lines)
                error_message = f"Invalid device names: {', '.join(invalid_devices)}. Use search_entities or list_devices to find correct names."
                
                return {
                    "all_valid": False,
                    "valid_devices": valid_devices,
                    "invalid_devices": invalid_devices,
                    "suggestions": suggestions,
                    "error_message": error_message,
                    "detailed_report": detailed_report
                }
                
        except Exception as e:
            self.error_log(f"Error validating device names: {e}")
            return {
                "all_valid": True,  # Allow processing to continue on validation errors
                "valid_devices": device_names,
                "invalid_devices": [],
                "suggestions": [],
                "error_message": "",
                "detailed_report": ""
            }
    
    def _find_similar_device_names(self, target_name: str, existing_names: set) -> List[str]:
        """
        Find device names similar to the target name using simple string matching.
        
        Args:
            target_name: The device name to find matches for
            existing_names: Set of all existing device names
            
        Returns:
            List of similar device names, sorted by relevance
        """
        try:
            target_lower = target_name.lower()
            target_words = set(target_lower.split())
            
            matches = []
            
            for name in existing_names:
                if not name:
                    continue
                    
                name_lower = name.lower()
                name_words = set(name_lower.split())
                
                # Calculate similarity score
                score = 0
                
                # Exact substring match (highest score)
                if target_lower in name_lower or name_lower in target_lower:
                    score += 100
                
                # Word overlap
                common_words = target_words.intersection(name_words)
                if common_words:
                    word_score = len(common_words) * 10
                    score += word_score
                
                # Character similarity (simple approach)
                if len(target_name) > 2 and len(name) > 2:
                    common_chars = set(target_lower).intersection(set(name_lower))
                    char_score = len(common_chars)
                    score += char_score
                
                if score > 0:
                    matches.append((name, score))
            
            # Sort by score (highest first) and return names only
            matches.sort(key=lambda x: x[1], reverse=True)
            return [match[0] for match in matches[:5]]  # Top 5 matches
            
        except Exception as e:
            self.debug_log(f"Error finding similar device names: {e}")
            return []
    
    def _is_valid_property_value(self, value) -> bool:
        """
        Check if a property value is suitable for historical analysis.
        
        Args:
            value: Property value to check
            
        Returns:
            True if value is suitable for historical tracking
        """
        if value is None:
            return False
        
        # Accept basic data types
        if isinstance(value, (int, float, bool)):
            return True
        
        # Accept strings but filter out very long ones (likely descriptions/configs)
        if isinstance(value, str):
            if len(value) > 100:  # Skip long strings
                return False
            # Skip obvious non-state values
            if value.lower() in {'plugin', 'device', 'none', 'null', ''}:
                return False
            return True
        
        # Reject complex objects
        return False
    
    def _calculate_summary_statistics(
        self, results: List[str], devices: List[str], days: int, duration: float
    ) -> Dict[str, Any]:
        """
        Calculate enhanced summary statistics from analysis results.
        
        Args:
            results: List of formatted result messages
            devices: List of analyzed device names
            days: Number of days analyzed
            duration: Analysis duration in seconds
            
        Returns:
            Dictionary of summary statistics
        """
        stats = {
            "total_state_changes": len(results),
            "devices_with_data": len(devices),
            "analysis_period_days": days,
            "analysis_duration_seconds": duration,
            "avg_changes_per_device": len(results) / len(devices) if devices else 0,
            "avg_changes_per_day": len(results) / days if days > 0 else 0
        }
        
        # Add time-based analysis if we have results
        if results:
            # Parse timestamps from results to get activity patterns
            activity_hours = {}
            for result in results:
                # Extract time patterns (simplified for now)
                if "from" in result and "to" in result:
                    # Count state changes by hour of day
                    pass  # Could be enhanced to extract actual patterns
            
            stats["activity_summary"] = "State changes distributed across analysis period"
        
        return stats
    
    def _format_analysis_report(
        self, results: List[str], entities: List[str], days: int, stats: Dict[str, Any], entity_classification: Dict[str, Any] = None
    ) -> str:
        """
        Format analysis results into a well-organized report.
        
        Args:
            results: List of state change messages
            entities: List of analyzed entity names
            days: Number of days analyzed
            stats: Summary statistics
            entity_classification: Optional entity type breakdown
            
        Returns:
            Formatted report string
        """
        report_lines = []
        
        # Header
        report_lines.append("=" * 60)
        report_lines.append(f"HISTORICAL DATA ANALYSIS REPORT")
        report_lines.append("=" * 60)
        report_lines.append(f"Analysis Period: Last {days} days")
        
        # Show entity breakdown if available
        if entity_classification:
            devices = entity_classification.get("devices", [])
            variables = entity_classification.get("variables", [])
            report_lines.append(f"Entities Analyzed: {len(entities)} ({len(devices)} devices, {len(variables)} variables)")
        else:
            report_lines.append(f"Entities Analyzed: {len(entities)}")
            
        report_lines.append(f"Total State Changes: {len(results)}")
        
        if stats.get("avg_changes_per_device"):
            report_lines.append(f"Average Changes per Device: {stats['avg_changes_per_device']:.1f}")
        if stats.get("avg_changes_per_day"):
            report_lines.append(f"Average Changes per Day: {stats['avg_changes_per_day']:.1f}")
        
        report_lines.append("")
        report_lines.append("DEVICE STATE HISTORY:")
        report_lines.append("-" * 60)
        
        # Group results by device for better organization
        device_results = {}
        for result in results:
            # Extract device name from result (first word before period or space)
            device_name = result.split('.')[0] if '.' in result else result.split(' ')[0]
            if device_name not in device_results:
                device_results[device_name] = []
            device_results[device_name].append(result)
        
        # Format results by device
        for device_name in sorted(device_results.keys()):
            report_lines.append(f"\n{device_name}:")
            for result in device_results[device_name]:
                report_lines.append(f"  • {result}")
        
        report_lines.append("")
        report_lines.append("=" * 60)
        
        # Add completion time if available
        if stats.get("analysis_duration_seconds") is not None:
            report_lines.append(f"Analysis completed in {stats['analysis_duration_seconds']:.2f} seconds")
        
        return "\n".join(report_lines)
    
    def _get_historical_variable_data(
        self, variable_name: str, time_range_days: int = 60
    ) -> List[str]:
        """
        Query InfluxDB for historical variable data and return formatted results.
        
        Args:
            variable_name: The variable name to query data for
            time_range_days: Number of days to look back for historical data
            
        Returns:
            List of formatted messages describing variable value changes
        """
        try:
            client = InfluxDBClient(logger=self.logger)
            query_builder = InfluxDBQueryBuilder(logger=self.logger)
            
            if not client.is_enabled() or not client.test_connection():
                return []
            
            # Build and execute query for variable changes
            query = query_builder.build_variable_history_query(
                variable_name=variable_name,
                time_range_days=time_range_days
            )
            
            results = client.execute_query(query)
            if not results:
                self.debug_log(f"InfluxDB query returned no results for variable {variable_name}")
                return []
            
            self.debug_log(f"InfluxDB returned {len(results)} raw records for variable {variable_name}")
            
            # Convert to formatted value change messages
            formatted_results = []
            saved_value = None
            from_timestamp = None
            
            for data_record in results:
                record_time_str = data_record.get("time")
                if not record_time_str:
                    continue
                
                timestamp_local = self._convert_to_local_timezone(record_time_str)
                field_value = data_record.get("value")
                
                if saved_value is None:
                    from_timestamp = timestamp_local
                    saved_value = field_value
                elif saved_value != field_value and from_timestamp is not None:
                    # Format duration in a more readable way
                    duration_str = self._format_duration(
                        from_timestamp, timestamp_local
                    )
                    
                    # Format timestamps with timezone info
                    from_str = from_timestamp.strftime("%Y-%m-%d %H:%M:%S %Z")
                    to_str = timestamp_local.strftime("%Y-%m-%d %H:%M:%S %Z")
                    
                    # Format the variable value (simplified formatting)
                    value_str = self._format_variable_value(saved_value)
                    
                    message = (
                        f"Variable '{variable_name}' was {value_str} for {duration_str}, "
                        f"from {from_str} to {to_str}"
                    )
                    formatted_results.append(message)
                    self.debug_log(message)
                    from_timestamp = timestamp_local
                    saved_value = field_value
            
            # Handle final value (current state)
            to_timestamp = datetime.now().astimezone()
            if from_timestamp is not None and saved_value is not None:
                # Format duration in a more readable way
                duration_str = self._format_duration(
                    from_timestamp, to_timestamp
                )
                
                # Format timestamps with timezone info
                from_str = from_timestamp.strftime("%Y-%m-%d %H:%M:%S %Z")
                
                # Format the variable value (simplified formatting)
                final_value = self._format_variable_value(saved_value)
                
                message = (
                    f"Variable '{variable_name}' is currently {final_value} (for {duration_str}), "
                    f"since {from_str}"
                )
                formatted_results.append(message)
            
            return formatted_results
            
        except Exception as e:
            self.debug_log(f"Error querying variable {variable_name}: {e}")
            return []
    
    def _format_variable_value(self, value) -> str:
        """
        Format variable value for display (simpler than device states).
        
        Args:
            value: Raw variable value
            
        Returns:
            Formatted value string
        """
        if value is None:
            return "null"
        
        # Handle boolean-like values
        if isinstance(value, bool):
            return "true" if value else "false"
        
        # Handle string values
        if isinstance(value, str):
            value_str = value.strip()
            # Keep original string but limit length for readability
            if len(value_str) > 100:
                return f'"{value_str[:97]}..."'
            else:
                return f'"{value_str}"'
        
        # Handle numeric values
        if isinstance(value, (int, float)):
            if isinstance(value, float) and value == int(value):
                return str(int(value))
            elif isinstance(value, float):
                return f"{value:.3f}".rstrip('0').rstrip('.')
            else:
                return str(value)
        
        # Fallback for other types
        return str(value)
    
    def _validate_entity_names(self, entity_names: List[str], entity_type: str) -> Dict[str, Any]:
        """
        Validate entity names and classify them as devices or variables.
        
        Args:
            entity_names: List of entity names to validate
            entity_type: Expected entity type ("auto", "devices", "variables", "mixed")
            
        Returns:
            Dictionary with validation results and entity classification
        """
        try:
            # Get all available devices and variables
            all_devices = self.data_provider.get_all_devices()
            all_variables = self.data_provider.get_all_variables()
            
            device_names = {device.get("name", "") for device in all_devices if device.get("name")}
            variable_names = {var.get("name", "") for var in all_variables if var.get("name")}
            
            valid_entities = []
            invalid_entities = []
            suggestions = []
            
            # Classify entities
            classified_devices = []
            classified_variables = []
            
            # Check each entity name
            for entity_name in entity_names:
                is_device = entity_name in device_names
                is_variable = entity_name in variable_names
                
                if is_device and is_variable:
                    # Ambiguous - prefer based on entity_type hint
                    if entity_type == "variables":
                        classified_variables.append(entity_name)
                        valid_entities.append(entity_name)
                    else:
                        # Default to device for ambiguous cases
                        classified_devices.append(entity_name)
                        valid_entities.append(entity_name)
                elif is_device:
                    classified_devices.append(entity_name)
                    valid_entities.append(entity_name)
                elif is_variable:
                    classified_variables.append(entity_name)
                    valid_entities.append(entity_name)
                else:
                    invalid_entities.append(entity_name)
                    
                    # Find similar names in both devices and variables
                    all_names = device_names.union(variable_names)
                    similar_names = self._find_similar_device_names(entity_name, all_names)
                    if similar_names:
                        suggestions.append({
                            "invalid_name": entity_name,
                            "suggestions": similar_names[:3]
                        })
            
            # Validate entity type consistency
            entity_type_error = None
            if entity_type == "devices" and classified_variables:
                entity_type_error = f"Expected only devices, but found variables: {classified_variables}"
            elif entity_type == "variables" and classified_devices:
                entity_type_error = f"Expected only variables, but found devices: {classified_devices}"
            
            all_valid = len(invalid_entities) == 0 and entity_type_error is None
            
            entity_classification = {
                "devices": classified_devices,
                "variables": classified_variables,
                "detected_type": "mixed" if (classified_devices and classified_variables) else 
                               "devices" if classified_devices else
                               "variables" if classified_variables else "none"
            }
            
            if all_valid:
                return {
                    "all_valid": True,
                    "valid_entities": valid_entities,
                    "invalid_entities": [],
                    "suggestions": [],
                    "error_message": "",
                    "detailed_report": "",
                    "entity_classification": entity_classification
                }
            else:
                # Create detailed error report
                error_lines = []
                
                if entity_type_error:
                    error_lines.append(f"Entity type mismatch: {entity_type_error}")
                
                if invalid_entities:
                    error_lines.append(f"Entity validation failed. {len(invalid_entities)} of {len(entity_names)} entities not found:")
                    
                    for invalid_entity in invalid_entities:
                        error_lines.append(f"  ❌ '{invalid_entity}' - NOT FOUND")
                        
                        # Add suggestions if available
                        entity_suggestions = next(
                            (item["suggestions"] for item in suggestions if item["invalid_name"] == invalid_entity),
                            []
                        )
                        if entity_suggestions:
                            error_lines.append(f"     💡 Did you mean: {', '.join(entity_suggestions)}")
                
                if valid_entities:
                    if classified_devices:
                        error_lines.append(f"\n✅ Valid devices found: {', '.join(classified_devices)}")
                    if classified_variables:
                        error_lines.append(f"✅ Valid variables found: {', '.join(classified_variables)}")
                
                error_lines.extend([
                    "\n📋 To find correct entity names, use:",
                    "  • search_entities('your entity description')",
                    "  • list_devices() to see all devices", 
                    "  • list_variables() to see all variables"
                ])
                
                detailed_report = "\n".join(error_lines)
                
                # Build appropriate error message
                if entity_type_error and invalid_entities:
                    error_message = f"{entity_type_error}. Also invalid entity names: {', '.join(invalid_entities)}."
                elif entity_type_error:
                    error_message = entity_type_error
                elif invalid_entities:
                    error_message = f"Invalid entity names: {', '.join(invalid_entities)}. Use search tools to find correct names."
                else:
                    error_message = "Validation failed"
                
                return {
                    "all_valid": False,
                    "valid_entities": valid_entities,
                    "invalid_entities": invalid_entities,
                    "suggestions": suggestions,
                    "error_message": error_message,
                    "detailed_report": detailed_report,
                    "entity_classification": entity_classification
                }
                
        except Exception as e:
            self.error_log(f"Error validating entity names: {e}")
            # Fallback classification (assume all are devices for backward compatibility)
            return {
                "all_valid": True,
                "valid_entities": entity_names,
                "invalid_entities": [],
                "suggestions": [],
                "error_message": "",
                "detailed_report": "",
                "entity_classification": {
                    "devices": entity_names,
                    "variables": [],
                    "detected_type": "devices"
                }
            }