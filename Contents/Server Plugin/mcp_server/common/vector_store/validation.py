"""
Vector store validation utilities for comprehensive data consistency checking.
"""

import json
import logging
from typing import Dict, List, Any, Optional, Tuple, Set
from enum import Enum

logger = logging.getLogger("Plugin")


class ValidationIssueType(Enum):
    """Types of validation issues that can be detected."""
    MISSING_RECORD = "missing_record"           # Entity not in vector store
    HASH_MISMATCH = "hash_mismatch"            # Static fields changed
    MISSING_KEYWORDS = "missing_keywords"       # No semantic keywords generated
    INVALID_EMBEDDING = "invalid_embedding"     # Empty or malformed embedding
    CORRUPTED_DATA = "corrupted_data"          # Unparseable stored data


class ValidationIssue:
    """Represents a validation issue found during consistency checking."""
    
    def __init__(self, entity_id: int, issue_type: ValidationIssueType, details: str = ""):
        self.entity_id = entity_id
        self.issue_type = issue_type
        self.details = details
    
    def __str__(self):
        return f"{self.issue_type.value}[{self.entity_id}]: {self.details}"


class ValidationResult:
    """Results of validation process with categorized issues."""
    
    def __init__(self):
        self.issues: List[ValidationIssue] = []
        self.valid_count = 0
        self.total_checked = 0
    
    def add_issue(self, entity_id: int, issue_type: ValidationIssueType, details: str = ""):
        """Add a validation issue."""
        issue = ValidationIssue(entity_id, issue_type, details)
        self.issues.append(issue)
        # Validation issue found
    
    def add_valid(self):
        """Mark an entity as valid."""
        self.valid_count += 1
        self.total_checked += 1
    
    def get_issues_by_type(self, issue_type: ValidationIssueType) -> List[ValidationIssue]:
        """Get all issues of a specific type."""
        return [issue for issue in self.issues if issue.issue_type == issue_type]
    
    def get_entity_ids_by_type(self, issue_type: ValidationIssueType) -> Set[int]:
        """Get entity IDs that have a specific issue type."""
        return {issue.entity_id for issue in self.issues if issue.issue_type == issue_type}
    
    def has_issues(self) -> bool:
        """Check if any validation issues were found."""
        return len(self.issues) > 0
    
    def summary(self) -> Dict[str, int]:
        """Get summary of validation results."""
        summary = {
            "total_checked": self.total_checked,
            "valid_count": self.valid_count,
            "total_issues": len(self.issues)
        }
        
        # Count issues by type
        for issue_type in ValidationIssueType:
            count = len(self.get_issues_by_type(issue_type))
            if count > 0:
                summary[issue_type.value] = count
                
        return summary


def load_validation_data(table, logger) -> Dict[int, Dict[str, Any]]:
    """
    Load comprehensive validation data from vector store table.
    
    Args:
        table: LanceDB table reference
        logger: Logger instance
        
    Returns:
        Dictionary mapping entity_id to validation data
    """
    try:
        # Load all necessary fields for validation
        # IMPORTANT: Must specify a large limit to get all records, otherwise LanceDB defaults to 10
        existing_rows = table.search().limit(999999).to_list()
        # Load validation data
        
        validation_data = {}
        for row in existing_rows:
            try:
                entity_id = row.get("id")
                if entity_id is None:
                    continue
                
                # Extract validation-relevant fields
                validation_data[entity_id] = {
                    "hash": row.get("hash", ""),
                    "text": row.get("text", ""),
                    "embedding": row.get("embedding", []),
                    "name": row.get("name", ""),
                    "data": row.get("data", "{}")
                }
                
            except Exception as row_error:
                # Skip invalid row
                continue
        
        return validation_data
        
    except Exception as e:
        # Failed to load validation data
        return {}


def detect_keyword_completeness(text: str, entity_name: str) -> bool:
    """
    Detect if the text field contains generated semantic keywords.
    
    Args:
        text: The text field from the vector store
        entity_name: Name of the entity for comparison
        
    Returns:
        True if keywords appear to be generated, False otherwise
    """
    if not text or not text.strip():
        return False
    
    try:
        # Try to parse as JSON first (basic format)
        text_data = json.loads(text)
        
        # If it's just basic JSON without enhancement, keywords are missing
        if isinstance(text_data, dict):
            # Check if it contains only basic fields (no semantic enhancement)
            basic_fields = {"name", "description", "model", "deviceTypeId", "address"}
            text_fields = set(text_data.keys())
            
            # If it only contains basic fields, no keywords were added
            if text_fields.issubset(basic_fields):
                return False
        
        # Check if the text contains semantic keywords beyond the entity name
        text_lower = text.lower()
        name_lower = entity_name.lower() if entity_name else ""
        
        # Look for common semantic keywords that wouldn't be in basic JSON
        semantic_indicators = [
            "lighting", "dimmer", "switch", "sensor", "control", "automation",
            "temperature", "motion", "contact", "security", "climate", "hvac",
            "scene", "mood", "schedule", "timer", "relay", "power", "energy"
        ]
        
        # Count semantic indicators not present in the entity name
        semantic_count = 0
        for indicator in semantic_indicators:
            if indicator in text_lower and indicator not in name_lower:
                semantic_count += 1
        
        # If we found multiple semantic indicators, keywords were likely generated
        return semantic_count >= 2
        
    except json.JSONDecodeError:
        # If it's not JSON, it might be enhanced text with keywords
        # Non-JSON text likely indicates keyword enhancement
        return len(text.split()) > len(entity_name.split()) + 5
    except Exception:
        # On any error, assume keywords are missing to be safe
        return False


def validate_embedding(embedding: List[float], expected_dimension: int = 1536) -> bool:
    """
    Validate that an embedding vector is properly formed.
    
    Args:
        embedding: The embedding vector
        expected_dimension: Expected dimension (default for text-embedding-3-small)
        
    Returns:
        True if embedding is valid, False otherwise
    """
    if not embedding:
        return False
    
    if not isinstance(embedding, list):
        return False
    
    if len(embedding) != expected_dimension:
        return False
    
    # Check if all values are valid floats
    try:
        for val in embedding:
            if not isinstance(val, (int, float)) or val != val:  # NaN check
                return False
        return True
    except:
        return False


def validate_stored_data(data_json: str) -> bool:
    """
    Validate that stored entity data can be parsed.
    
    Args:
        data_json: JSON string of stored entity data
        
    Returns:
        True if data is valid, False otherwise
    """
    if not data_json:
        return False
    
    try:
        data = json.loads(data_json)
        # Check that it's a dictionary with at least an ID
        return isinstance(data, dict) and "id" in data
    except:
        return False


def perform_comprehensive_validation(
    current_entities: List[Dict[str, Any]],
    validation_data: Dict[int, Dict[str, Any]], 
    entity_type: str,
    hash_function: callable
) -> ValidationResult:
    """
    Perform comprehensive validation of entities against stored data.
    
    Args:
        current_entities: Current entities from Indigo
        validation_data: Loaded validation data from vector store
        entity_type: Type of entities being validated
        hash_function: Function to calculate entity hash
        
    Returns:
        ValidationResult with all detected issues
    """
    result = ValidationResult()
    
    # Track entity IDs
    current_ids = {e["id"] for e in current_entities if e.get("id") is not None}
    stored_ids = set(validation_data.keys())
    
    # Validate entities
    
    # Check each current entity
    for entity in current_entities:
        entity_id = entity.get("id")
        if entity_id is None:
            continue
            
        result.total_checked += 1
        entity_issues = []
        
        if entity_id not in stored_ids:
            # Missing from vector store entirely
            result.add_issue(entity_id, ValidationIssueType.MISSING_RECORD, "Not found in vector store")
            continue
        
        stored_data = validation_data[entity_id]
        
        # Validate hash (static fields)
        current_hash = hash_function(entity, entity_type)
        stored_hash = stored_data.get("hash", "")
        if current_hash != stored_hash:
            result.add_issue(entity_id, ValidationIssueType.HASH_MISMATCH, 
                           f"Hash changed (was: {stored_hash[:8]}..., now: {current_hash[:8]}...)")
            entity_issues.append("hash_mismatch")
        
        # Validate stored data integrity
        stored_json = stored_data.get("data", "{}")
        if not validate_stored_data(stored_json):
            result.add_issue(entity_id, ValidationIssueType.CORRUPTED_DATA, "Cannot parse stored entity data")
            entity_issues.append("corrupted_data")
        
        # Validate embedding
        embedding = stored_data.get("embedding", [])
        if not validate_embedding(embedding):
            result.add_issue(entity_id, ValidationIssueType.INVALID_EMBEDDING, 
                           f"Invalid embedding (length: {len(embedding) if embedding else 0})")
            entity_issues.append("invalid_embedding")
        
        # Validate keyword completeness (for devices)
        if entity_type == "devices":
            text = stored_data.get("text", "")
            entity_name = entity.get("name", "")
            if not detect_keyword_completeness(text, entity_name):
                result.add_issue(entity_id, ValidationIssueType.MISSING_KEYWORDS, "No semantic keywords detected")
                entity_issues.append("missing_keywords")
        
        # If no issues, mark as valid
        if not entity_issues:
            result.add_valid()
    
    # Check for orphaned records (in store but not in current entities)
    orphaned_ids = stored_ids - current_ids
    for orphaned_id in orphaned_ids:
        result.add_issue(orphaned_id, ValidationIssueType.MISSING_RECORD, "Entity no longer exists in Indigo")
    
    return result


def prioritize_updates(validation_result: ValidationResult) -> Dict[str, List[int]]:
    """
    Prioritize updates based on issue severity and impact.
    
    Args:
        validation_result: Results from comprehensive validation
        
    Returns:
        Dictionary with prioritized update lists
    """
    # Critical: Issues that prevent search functionality
    critical_ids = set()
    critical_ids.update(validation_result.get_entity_ids_by_type(ValidationIssueType.MISSING_RECORD))
    critical_ids.update(validation_result.get_entity_ids_by_type(ValidationIssueType.INVALID_EMBEDDING))
    critical_ids.update(validation_result.get_entity_ids_by_type(ValidationIssueType.CORRUPTED_DATA))
    
    # High: Static fields changed, affects search accuracy
    high_ids = validation_result.get_entity_ids_by_type(ValidationIssueType.HASH_MISMATCH)
    # Remove critical issues from high priority (already handled)
    high_ids = high_ids - critical_ids
    
    # Medium: Missing keywords, affects search quality but doesn't break functionality  
    medium_ids = validation_result.get_entity_ids_by_type(ValidationIssueType.MISSING_KEYWORDS)
    # Remove higher priority issues
    medium_ids = medium_ids - critical_ids - high_ids
    
    return {
        "critical": list(critical_ids),
        "high": list(high_ids), 
        "medium": list(medium_ids)
    }


def log_validation_summary(validation_result: ValidationResult, entity_type: str, logger):
    """
    Log a comprehensive summary of validation results.
    
    Args:
        validation_result: Results from validation
        entity_type: Type of entities validated
        logger: Logger instance
    """
    summary = validation_result.summary()
    
    if not validation_result.has_issues():
        return
    
    # Only log if there are significant issues
    if summary['total_issues'] > 10:
        logger.debug(f"Validation found {summary['total_issues']} issues in {entity_type} (valid: {summary['valid_count']}/{summary['total_checked']})")