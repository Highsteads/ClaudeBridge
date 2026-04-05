"""
Energy intelligence handler for ClaudeBridge MCP server.

Reads SigenEnergyManager's daily rotating log files to provide historical
energy analysis without requiring InfluxDB.

Tools:
  - energy_log_days(days=7)       : return raw log entries for the last N days
  - energy_daily_summary(days=14) : parse log files into per-day kWh totals
  - energy_compare(days_a, days_b): compare two N-day windows (e.g. this week vs last)
"""

import logging
import os
import re
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

try:
    import indigo
except ImportError:
    pass

from ..base_handler import BaseToolHandler
from ...adapters.data_provider import DataProvider

SIGEN_PLUGIN_ID = "com.clives.indigoplugin.sigenergy-energy-manager"

# Patterns to extract from SigenEnergyManager log lines
_DAILY_PV_RE      = re.compile(r"\[Daily\].*?PV[:\s]+([\d.]+)\s*kWh", re.I)
_DAILY_IMPORT_RE  = re.compile(r"\[Daily\].*?import[:\s]+([\d.]+)\s*kWh", re.I)
_DAILY_EXPORT_RE  = re.compile(r"\[Daily\].*?export[:\s]+([\d.]+)\s*kWh", re.I)
_DAILY_HOME_RE    = re.compile(r"\[Daily\].*?home[:\s]+([\d.]+)\s*kWh", re.I)
_DAILY_LINE_RE    = re.compile(r"\[Daily\]", re.I)
_SOC_RE           = re.compile(r"SOC=([\d.]+)%")
_MANAGER_RE       = re.compile(r"\[Manager\].*?Action=(\w+)")


def _sigen_log_dir() -> Optional[str]:
    """Return the SigenEnergyManager log directory path."""
    base = indigo.server.getInstallFolderPath()
    log_dir = os.path.join(
        base, "Preferences", "Plugins", SIGEN_PLUGIN_ID, "logs"
    )
    return log_dir if os.path.isdir(log_dir) else None


def _log_file_for_date(log_dir: str, date: datetime) -> Optional[str]:
    path = os.path.join(log_dir, date.strftime("%Y-%m-%d") + ".log")
    return path if os.path.isfile(path) else None


def _parse_daily_line(line: str) -> Optional[Dict[str, Any]]:
    """
    Parse a [Daily] summary line from SigenEnergyManager log.
    Example: 23:59:59 [INFO   ] [Daily] PV: 45.3 kWh  Import: 0.0 kWh  Export: 12.1 kWh  Home: 18.7 kWh
    """
    if not _DAILY_LINE_RE.search(line):
        return None

    result: Dict[str, Any] = {}
    for label, pattern in (
        ("pv_kwh",     _DAILY_PV_RE),
        ("import_kwh", _DAILY_IMPORT_RE),
        ("export_kwh", _DAILY_EXPORT_RE),
        ("home_kwh",   _DAILY_HOME_RE),
    ):
        m = pattern.search(line)
        if m:
            try:
                result[label] = float(m.group(1))
            except ValueError:
                pass
    return result if result else None


class EnergyToolsHandler(BaseToolHandler):
    """Handler for SigenEnergyManager historical energy data."""

    def __init__(
        self,
        data_provider: DataProvider,
        logger: Optional[logging.Logger] = None,
    ):
        super().__init__(tool_name="energy_tools", logger=logger)
        self.data_provider = data_provider

    # ────────────────────────────────────────────────────────────────────────
    # energy_log_days
    # ────────────────────────────────────────────────────────────────────────

    def energy_log_days(self, days: int = 3) -> Dict[str, Any]:
        """
        Return raw log lines from the last N days of SigenEnergyManager logs.
        Useful for asking Claude to reason about specific events.
        """
        self.log_incoming_request("energy_log_days", {"days": days})
        try:
            log_dir = _sigen_log_dir()
            if not log_dir:
                return {"success": False,
                        "error": "SigenEnergyManager log directory not found"}

            days = max(1, min(days, 14))  # cap at 14 days
            today  = datetime.now()
            result_lines: Dict[str, List[str]] = {}

            for i in range(days):
                date    = today - timedelta(days=i)
                logpath = _log_file_for_date(log_dir, date)
                if not logpath:
                    continue
                try:
                    with open(logpath, "r", encoding="utf-8", errors="replace") as fh:
                        lines = [l.rstrip() for l in fh if l.strip()]
                    result_lines[date.strftime("%Y-%m-%d")] = lines
                except OSError:
                    pass

            result = {
                "success":    True,
                "days":       days,
                "log_dir":    log_dir,
                "dates_found": list(result_lines.keys()),
                "logs":       result_lines,
            }
            total = sum(len(v) for v in result_lines.values())
            self.log_tool_outcome("energy_log_days", True,
                                  f"{total} log lines across {len(result_lines)} days")
            return result
        except Exception as exc:
            return self.handle_exception(exc, "energy_log_days")

    # ────────────────────────────────────────────────────────────────────────
    # energy_daily_summary
    # ────────────────────────────────────────────────────────────────────────

    def energy_daily_summary(self, days: int = 14) -> Dict[str, Any]:
        """
        Parse SigenEnergyManager daily log files and return per-day kWh totals:
        PV generated, grid imported, grid exported, home consumption.
        """
        self.log_incoming_request("energy_daily_summary", {"days": days})
        try:
            log_dir = _sigen_log_dir()
            if not log_dir:
                return {"success": False,
                        "error": "SigenEnergyManager log directory not found"}

            days  = max(1, min(days, 90))
            today = datetime.now()
            daily: List[Dict[str, Any]] = []
            totals = {"pv_kwh": 0.0, "import_kwh": 0.0,
                      "export_kwh": 0.0, "home_kwh": 0.0}

            for i in range(days):
                date    = today - timedelta(days=i)
                logpath = _log_file_for_date(log_dir, date)
                if not logpath:
                    continue

                day_data: Dict[str, Any] = {"date": date.strftime("%Y-%m-%d")}
                max_soc, min_soc = 0.0, 100.0
                soc_readings     = 0

                try:
                    with open(logpath, "r", encoding="utf-8", errors="replace") as fh:
                        for line in fh:
                            # Daily summary line
                            parsed = _parse_daily_line(line)
                            if parsed:
                                day_data.update(parsed)
                            # SOC tracking
                            m = _SOC_RE.search(line)
                            if m:
                                soc = float(m.group(1))
                                max_soc = max(max_soc, soc)
                                min_soc = min(min_soc, soc)
                                soc_readings += 1
                except OSError:
                    continue

                if soc_readings > 0:
                    day_data["max_soc_pct"] = round(max_soc, 1)
                    day_data["min_soc_pct"] = round(min_soc, 1)

                if day_data.get("pv_kwh") is not None or soc_readings > 0:
                    daily.append(day_data)
                    for k in ("pv_kwh", "import_kwh", "export_kwh", "home_kwh"):
                        totals[k] = round(totals[k] + day_data.get(k, 0.0), 2)

            daily.sort(key=lambda x: x["date"])

            # Self-sufficiency across the period
            total_home   = totals["home_kwh"]
            total_import = totals["import_kwh"]
            self_suff    = (
                round((1 - total_import / total_home) * 100, 1)
                if total_home > 0 else None
            )

            result = {
                "success":         True,
                "days_requested":  days,
                "days_found":      len(daily),
                "period_totals":   {**totals,
                                    "self_sufficiency_pct": self_suff},
                "daily":           daily,
            }
            self.log_tool_outcome("energy_daily_summary", True,
                                  f"{len(daily)} days parsed")
            return result
        except Exception as exc:
            return self.handle_exception(exc, "energy_daily_summary")

    # ────────────────────────────────────────────────────────────────────────
    # energy_compare
    # ────────────────────────────────────────────────────────────────────────

    def energy_compare(
        self,
        period_a_days: int = 7,
        period_b_days: int = 7,
        period_b_offset: int = 7,
    ) -> Dict[str, Any]:
        """
        Compare two rolling periods.
        period_a = last period_a_days days (most recent)
        period_b = period_b_days days ending period_b_offset days ago

        Example: compare this week (7d) vs last week (7d starting 7d ago)
          energy_compare(7, 7, 7)
        """
        self.log_incoming_request("energy_compare",
                                  {"period_a_days": period_a_days,
                                   "period_b_days": period_b_days,
                                   "period_b_offset": period_b_offset})
        try:
            log_dir = _sigen_log_dir()
            if not log_dir:
                return {"success": False,
                        "error": "SigenEnergyManager log directory not found"}

            today = datetime.now()

            def _sum_period(start_offset: int, n_days: int) -> Dict[str, Any]:
                totals = {"pv_kwh": 0.0, "import_kwh": 0.0,
                          "export_kwh": 0.0, "home_kwh": 0.0}
                dates  = []
                for i in range(start_offset, start_offset + n_days):
                    date    = today - timedelta(days=i)
                    logpath = _log_file_for_date(log_dir, date)
                    if not logpath:
                        continue
                    dates.append(date.strftime("%Y-%m-%d"))
                    try:
                        with open(logpath, "r", encoding="utf-8",
                                  errors="replace") as fh:
                            for line in fh:
                                parsed = _parse_daily_line(line)
                                if parsed:
                                    for k in totals:
                                        totals[k] = round(
                                            totals[k] + parsed.get(k, 0.0), 2)
                    except OSError:
                        pass
                home   = totals["home_kwh"]
                imp    = totals["import_kwh"]
                sself  = (round((1 - imp / home) * 100, 1)
                          if home > 0 else None)
                return {**totals,
                        "self_sufficiency_pct": sself,
                        "days_found": len(dates),
                        "dates": dates}

            a = _sum_period(0, period_a_days)
            b = _sum_period(period_b_offset, period_b_days)

            def _diff(ka, kb, key):
                va, vb = ka.get(key, 0) or 0, kb.get(key, 0) or 0
                delta  = round(va - vb, 2)
                pct    = round(delta / vb * 100, 1) if vb else None
                return {"a": va, "b": vb, "delta": delta, "pct_change": pct}

            result = {
                "success":    True,
                "period_a":   {"label": f"last {period_a_days} days", **a},
                "period_b":   {"label": f"{period_b_days} days ending "
                                        f"{period_b_offset}d ago",    **b},
                "comparison": {
                    k: _diff(a, b, k)
                    for k in ("pv_kwh", "import_kwh", "export_kwh", "home_kwh")
                },
            }
            self.log_tool_outcome("energy_compare", True,
                                  "Energy period comparison complete")
            return result
        except Exception as exc:
            return self.handle_exception(exc, "energy_compare")
