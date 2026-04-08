"""
Log query handler for MCP server.
"""

import logging
import os
import re
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional

from ...adapters.data_provider import DataProvider
from ..base_handler import BaseToolHandler

# ── Log-file location ────────────────────────────────────────────────────────
# Derive the Indigo Logs folder from this module's own path.
# This file lives at:
#   .../Indigo 2025.1/Plugins/Claude Bridge.indigoPlugin/
#              Contents/Server Plugin/mcp_server/tools/log_query/log_query_handler.py
# Going up 7 directories reaches the Indigo 2025.1 install root.
_HERE     = os.path.dirname(os.path.abspath(__file__))
_LOG_ROOT = os.path.normpath(os.path.join(_HERE, *([".."] * 7), "Logs"))

# Log file line format: "YYYY-MM-DD HH:MM:SS.mmm<TAB>Source<TAB>Message"
_LOG_LINE_RE = re.compile(
    r'^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d+)\t([^\t]*)\t(.*)$'
)


def _parse_time_param(value: str, today: date) -> Optional[datetime]:
    """Parse a time string into a datetime.

    Accepts:
      - "HH:MM:SS" or "HH:MM"              → today's date assumed
      - "YYYY-MM-DDTHH:MM:SS" or variants  → full datetime
      - "YYYY-MM-DD HH:MM:SS" or variants
    """
    value = value.strip()
    # Detect time-only by absence of date prefix
    if len(value) <= 8 and re.match(r'^\d{1,2}:\d{2}', value):
        for fmt in ("%H:%M:%S", "%H:%M"):
            try:
                return datetime.combine(today, datetime.strptime(value, fmt).time())
            except ValueError:
                continue
        return None
    # Full datetime
    for fmt in (
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%dT%H:%M",
        "%Y-%m-%d %H:%M",
    ):
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            continue
    return None


class LogQueryHandler(BaseToolHandler):
    """Handler for querying Indigo event log entries."""

    def __init__(
        self,
        data_provider: DataProvider,
        logger: Optional[logging.Logger] = None
    ):
        super().__init__(tool_name="log_query", logger=logger)
        self.data_provider = data_provider

    # ── Time-range file reader ────────────────────────────────────────────────

    def _read_log_range(
        self,
        after_dt:   Optional[datetime],
        before_dt:  Optional[datetime],
        line_count: Optional[int],
    ) -> List[Dict[str, Any]]:
        """Read log file(s) from disk and return entries in the time range.

        Entries are returned as dicts matching the format from
        indigo.server.getEventLogList():
          {"TimeStamp": str, "TypeStr": str, "Message": str}

        line_count limits the LAST N matching entries (most recent first).
        """
        start_date = (after_dt  or datetime.now()).date()
        end_date   = (before_dt or datetime.now()).date()

        results: List[Dict[str, Any]] = []
        current = start_date
        while current <= end_date:
            log_file = os.path.join(
                _LOG_ROOT, f"{current.strftime('%Y-%m-%d')} Events.txt"
            )
            if os.path.exists(log_file):
                try:
                    with open(log_file, "r", encoding="utf-8", errors="replace") as fh:
                        for line in fh:
                            m = _LOG_LINE_RE.match(line.rstrip("\n"))
                            if not m:
                                continue
                            ts_str, source, message = (
                                m.group(1), m.group(2), m.group(3)
                            )
                            try:
                                ts = datetime.strptime(ts_str[:19], "%Y-%m-%d %H:%M:%S")
                            except ValueError:
                                continue
                            if after_dt  and ts <= after_dt:
                                continue
                            if before_dt and ts >= before_dt:
                                continue
                            results.append({
                                "TimeStamp": ts_str,
                                "TypeStr":   source,
                                "Message":   message,
                            })
                except OSError as exc:
                    self.logger.warning(f"Could not read log file {log_file}: {exc}")
            current += timedelta(days=1)

        if line_count and len(results) > line_count:
            results = results[-line_count:]
        return results

    # ── Public tool method ────────────────────────────────────────────────────

    def query(
        self,
        line_count:     Optional[int]  = 20,
        show_timestamp: bool           = True,
        after:          Optional[str]  = None,
        before:         Optional[str]  = None,
    ) -> Dict[str, Any]:
        """Query Indigo event log entries.

        Without ``after``/``before``: returns the most recent ``line_count``
        entries from Indigo's in-memory log (same as before).

        With ``after`` and/or ``before``: reads from the on-disk log files and
        returns all entries in that window, capped at ``line_count``.

        Time formats accepted for ``after``/``before``:
          - "HH:MM:SS" or "HH:MM"         — today assumed
          - "YYYY-MM-DDTHH:MM:SS"         — full ISO datetime
          - "YYYY-MM-DD HH:MM:SS"

        Example: after="07:45:00", before="07:52:00"
        """
        params = {
            "line_count":     line_count,
            "show_timestamp": show_timestamp,
            "after":          after,
            "before":         before,
        }
        self.log_incoming_request("query", params)

        try:
            today = date.today()

            # ── Time-range path: read from disk ───────────────────────────────
            if after is not None or before is not None:
                after_dt = _parse_time_param(after, today) if after   else None
                before_dt = _parse_time_param(before, today) if before else None

                if after is not None and after_dt is None:
                    return {
                        "error":   f"Could not parse 'after' value: {after!r}",
                        "success": False,
                    }
                if before is not None and before_dt is None:
                    return {
                        "error":   f"Could not parse 'before' value: {before!r}",
                        "success": False,
                    }

                entries = self._read_log_range(after_dt, before_dt, line_count)
                result = {
                    "success":    True,
                    "count":      len(entries),
                    "entries":    entries,
                    "parameters": params,
                }
                self.log_tool_outcome(
                    "query", True, f"Retrieved {len(entries)} log entries (file scan)"
                )
                return result

            # ── Default path: recent entries from Indigo in-memory log ────────
            if line_count is not None and (
                not isinstance(line_count, int) or line_count <= 0
            ):
                self.log_tool_outcome("query", False, "Invalid line_count parameter")
                return {"error": "line_count must be a positive integer", "success": False}

            self.debug_log(
                f"Querying event log: {line_count} entries, timestamps={show_timestamp}"
            )
            log_entries = self.data_provider.get_event_log_list(
                line_count=line_count,
                show_timestamp=show_timestamp,
            )
            result = {
                "success":    True,
                "count":      len(log_entries),
                "entries":    log_entries,
                "parameters": params,
            }
            self.log_tool_outcome(
                "query", True, f"Retrieved {len(log_entries)} log entries",
                count=len(log_entries),
            )
            return result

        except Exception as e:
            return self.handle_exception(e, "querying event log")
