"""
Log query handler for MCP server.
"""

import logging
from typing import Dict, Any, Optional, List, Union

from ...adapters.data_provider import DataProvider
from ..base_handler import BaseToolHandler


class LogQueryHandler(BaseToolHandler):
    """Handler for querying Indigo event log entries."""

    def __init__(
        self,
        data_provider: DataProvider,
        logger: Optional[logging.Logger] = None
    ):
        """
        Initialize the log query handler.

        Args:
            data_provider: Data provider for log operations
            logger: Optional logger instance
        """
        super().__init__(tool_name="log_query", logger=logger)
        self.data_provider = data_provider

    def query(
        self,
        line_count: Optional[int] = 20,
        show_timestamp: bool = True
    ) -> Dict[str, Any]:
        """
        Query recent Indigo event log entries.

        Args:
            line_count: Number of log entries to return (default: 20)
            show_timestamp: Include timestamps in log entries (default: True)

        Returns:
            Dictionary with operation results including log entries
        """
        # Log incoming request
        params = {"line_count": line_count, "show_timestamp": show_timestamp}
        self.log_incoming_request("query", params)

        try:
            # Validate line_count
            if line_count is not None and (not isinstance(line_count, int) or line_count <= 0):
                error_result = {
                    "error": "line_count must be a positive integer",
                    "success": False
                }
                self.log_tool_outcome("query", False, "Invalid line_count parameter")
                return error_result

            # Query the event log
            self.debug_log(f"Querying event log: {line_count} entries, timestamps={show_timestamp}")

            log_entries = self.data_provider.get_event_log_list(
                line_count=line_count,
                show_timestamp=show_timestamp
            )

            # Format response
            result = {
                "success": True,
                "count": len(log_entries),
                "entries": log_entries,
                "parameters": {
                    "line_count": line_count,
                    "show_timestamp": show_timestamp
                }
            }

            # Log outcome
            self.log_tool_outcome(
                "query",
                True,
                f"Retrieved {len(log_entries)} log entries",
                count=len(log_entries)
            )

            return result

        except Exception as e:
            return self.handle_exception(e, f"querying event log")
