"""
Utilities for handling OpenAI response structures consistently.
Provides robust text extraction from various response types including GPT-5 reasoning items.
"""

import logging
from typing import Any, Union, List, Optional

logger = logging.getLogger("Plugin")


def extract_text_content(response: Any, context_name: str = "response") -> str:
    """
    Extract text content from various OpenAI response types.
    
    Handles:
    - Standard OpenAI ChatCompletion responses
    - String responses
    - List responses (from some LLM configurations)
    - ResponseReasoningItem objects (GPT-5 reasoning models)
    - Tool call responses
    - Various other response object types
    
    Args:
        response: Response object from OpenAI API
        context_name: Context name for error logging
        
    Returns:
        Extracted text content as string, empty string if extraction fails
    """
    try:
        # Handle None or empty responses
        if response is None:
            return ""
        
        # Handle string responses directly
        if isinstance(response, str):
            return response.strip()
        
        # Handle ChatCompletion responses (standard OpenAI format)
        if hasattr(response, 'choices') and response.choices:
            choice = response.choices[0]
            if hasattr(choice, 'message') and choice.message:
                content = choice.message.content
                if content:
                    return content.strip()
        
        # Handle list responses (common with some LLM configurations)
        if isinstance(response, list):
            if not response:
                return ""
            
            # Try to extract content from first valid item in list
            for i, item in enumerate(response):
                # Recursively extract from list items
                extracted = _extract_from_single_object(item, f"{context_name}-item-{i}")
                if extracted:
                    return extracted
            
            return ""
        
        # Handle single response objects (including ResponseReasoningItem)
        return _extract_from_single_object(response, context_name)
        
    except Exception as e:
        logger.error(f"Exception in text extraction for {context_name}: {e}")
        return ""


def _extract_from_single_object(response_obj: Any, context_name: str) -> str:
    """
    Extract text content from a single response object.
    
    Args:
        response_obj: Single response object (not a list)
        context_name: Context name for error logging
        
    Returns:
        Extracted text content as string
    """
    try:
        # Handle string responses directly
        if isinstance(response_obj, str):
            return response_obj.strip()
        
        # Check for content attribute (ResponseReasoningItem, etc.)
        if hasattr(response_obj, 'content'):
            content = response_obj.content
            if content is not None:
                # Handle content as a list of content items
                if isinstance(content, list):
                    for i, content_item in enumerate(content):
                        if hasattr(content_item, 'text') and content_item.text:
                            return str(content_item.text).strip()
                # Handle content as a string
                elif isinstance(content, str):
                    return content.strip()
                # Handle content as an object with text
                elif hasattr(content, 'text') and content.text:
                    return str(content.text).strip()
                # Fallback to string conversion of content
                else:
                    content_str = str(content).strip()
                    if content_str and content_str != "None":
                        return content_str
        
        # Check for text attribute
        if hasattr(response_obj, 'text') and response_obj.text:
            return str(response_obj.text).strip()
        
        # Check for message attribute
        if hasattr(response_obj, 'message') and response_obj.message:
            return str(response_obj.message).strip()
        
        # Check for output attribute (some response formats)
        if hasattr(response_obj, 'output') and response_obj.output:
            return str(response_obj.output).strip()
        
        # For ResponseReasoningItem and similar objects, try string conversion as fallback
        response_str = str(response_obj)
        if response_str and not response_str.startswith(f"{type(response_obj).__name__}("):
            return response_str.strip()
        
        # Final fallback - only log in debug mode
        if logger.isEnabledFor(logging.DEBUG):
            logger.debug(f"Could not extract text from {type(response_obj).__name__} for {context_name}")
        return ""
        
    except Exception as e:
        logger.error(f"Exception in single object text extraction for {context_name}: {e}")
        return ""


def is_tool_call_response(response: Any) -> bool:
    """
    Check if a response contains tool calls.
    
    Args:
        response: Response object to check
        
    Returns:
        True if response contains tool calls, False otherwise
    """
    try:
        # Check ChatCompletion response format
        if hasattr(response, 'choices') and response.choices:
            message = response.choices[0].message
            if hasattr(message, 'tool_calls') and message.tool_calls:
                return True
            if hasattr(message, 'function_call') and message.function_call:
                return True
        
        # Check dict format (from perform_completion)
        if isinstance(response, dict) and response.get('tool_calls'):
            return True
        
        return False
        
    except Exception as e:
        logger.debug(f"Error checking tool calls: {e}")
        return False


def extract_tool_calls(response: Any) -> List[dict]:
    """
    Extract tool calls from a response.
    
    Args:
        response: Response object containing tool calls
        
    Returns:
        List of tool call dictionaries
    """
    try:
        # Handle dict format (from perform_completion)
        if isinstance(response, dict) and response.get('tool_calls'):
            return response['tool_calls']
        
        # Handle ChatCompletion response format
        if hasattr(response, 'choices') and response.choices:
            message = response.choices[0].message
            tool_calls = []
            
            # Handle newer tool_calls format
            if hasattr(message, 'tool_calls') and message.tool_calls:
                for tc in message.tool_calls:
                    tool_calls.append({
                        "function": {
                            "name": tc.function.name,
                            "arguments": tc.function.arguments,
                        }
                    })
            
            # Handle older function_call format
            elif hasattr(message, 'function_call') and message.function_call:
                tool_calls.append({
                    "function": {
                        "name": message.function_call.name,
                        "arguments": message.function_call.arguments,
                    }
                })
            
            return tool_calls
        
        return []
        
    except Exception as e:
        logger.error(f"Error extracting tool calls: {e}")
        return []