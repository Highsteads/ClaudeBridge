"""
State filtering utilities for Indigo entities.
"""

from typing import Dict, List, Any, Optional, Union
import re


class StateFilter:
    """Shared state filtering logic for Indigo entities."""
    
    @staticmethod
    def filter_by_state(
        entities: List[Dict[str, Any]], 
        state_conditions: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """
        Filter entities by Indigo state conditions.
        
        Args:
            entities: List of entity dictionaries
            state_conditions: State requirements using Indigo state names
                Examples:
                - {"onState": True} - devices that are on
                - {"brightnessLevel": {"gt": 50}} - brightness greater than 50
                - {"onState": False, "errorState": ""} - off devices with no errors
                
        Returns:
            Filtered list of entities matching state conditions
        """
        if not state_conditions:
            return entities
            
        filtered = []
        for entity in entities:
            if StateFilter.matches_state(entity, state_conditions):
                filtered.append(entity)
                
        return filtered
    
    @staticmethod
    def matches_state(entity: Dict[str, Any], conditions: Dict[str, Any]) -> bool:
        """
        Check if an entity matches state conditions.
        
        Args:
            entity: Entity dictionary with state information
            conditions: State conditions to match
            
        Returns:
            True if entity matches all conditions
        """
        # Check direct entity properties (like onState)
        for key, expected_value in conditions.items():
            # Handle nested state conditions
            if isinstance(expected_value, dict):
                if not StateFilter._matches_complex_condition(entity, key, expected_value):
                    return False
            else:
                # Simple equality check
                # First check direct property
                if key in entity:
                    if entity[key] != expected_value:
                        return False
                # Then check in states dictionary if present
                elif "states" in entity and key in entity["states"]:
                    if entity["states"][key] != expected_value:
                        return False
                else:
                    # State not found, condition fails
                    return False
                    
        return True
    
    @staticmethod
    def _matches_complex_condition(
        entity: Dict[str, Any], 
        key: str, 
        condition: Dict[str, str]
    ) -> bool:
        """
        Handle complex conditions like greater than, less than, etc.
        
        Args:
            entity: Entity dictionary
            key: State key to check
            condition: Complex condition dict like {"gt": 50}
            
        Returns:
            True if condition is met
        """
        # Get the value from entity or states
        value = None
        if key in entity:
            value = entity[key]
        elif "states" in entity and key in entity["states"]:
            value = entity["states"][key]
        else:
            return False
            
        # Handle different operators
        for operator, expected in condition.items():
            if operator == "gt" and not (value > expected):
                return False
            elif operator == "gte" and not (value >= expected):
                return False
            elif operator == "lt" and not (value < expected):
                return False
            elif operator == "lte" and not (value <= expected):
                return False
            elif operator == "ne" and not (value != expected):
                return False
            elif operator == "eq" and not (value == expected):
                return False
            elif operator == "contains" and expected not in str(value):
                return False
            elif operator == "regex":
                if not re.match(expected, str(value)):
                    return False
                    
        return True
    
    @staticmethod
    def parse_state_requirements(query: str) -> Optional[Dict[str, Any]]:
        """
        Extract state requirements from natural language query.
        
        Args:
            query: Natural language search query
            
        Returns:
            Dictionary of state conditions or None if no state requirements detected
        """
        query_lower = query.lower()
        conditions = {}
        
        # Detect on/off states
        if any(word in query_lower for word in ["on", "active", "enabled", "turned on"]):
            conditions["onState"] = True
        elif any(word in query_lower for word in ["off", "inactive", "disabled", "turned off"]):
            conditions["onState"] = False
            
        # Detect brightness levels
        if "bright" in query_lower or "dim" in query_lower:
            if "bright" in query_lower:
                # Bright means > 50% brightness
                conditions["brightnessLevel"] = {"gt": 50}
            elif "dim" in query_lower:
                # Dim means <= 50% brightness
                conditions["brightnessLevel"] = {"lte": 50}
                
        # Detect error states
        if "error" in query_lower or "fault" in query_lower:
            if "no error" in query_lower or "without error" in query_lower:
                conditions["errorState"] = ""
            else:
                conditions["errorState"] = {"ne": ""}
                
        # Detect temperature-related states for sensors
        if "hot" in query_lower or "warm" in query_lower:
            conditions["temperature"] = {"gt": 75}
        elif "cold" in query_lower or "cool" in query_lower:
            conditions["temperature"] = {"lt": 65}
            
        return conditions if conditions else None
    
    @staticmethod
    def has_state_keywords(query: str) -> bool:
        """
        Check if query contains state-related keywords.
        
        Args:
            query: Natural language search query
            
        Returns:
            True if state keywords are detected
        """
        query_lower = query.lower()
        state_keywords = [
            r'\bon\b', r'\boff\b', r'\bactive\b', r'\binactive\b', r'\benabled\b', r'\bdisabled\b',
            r'\bbright\b', r'\bdim\b', r'\bturned on\b', r'\bturned off\b',
            r'\berror\b', r'\bfault\b', r'\bhot\b', r'\bcold\b', r'\bwarm\b', r'\bcool\b',
            r'\bopen\b', r'\bclosed\b', r'\blocked\b', r'\bunlocked\b'
        ]
        
        return any(re.search(pattern, query_lower) for pattern in state_keywords)