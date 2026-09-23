"""
Energy intelligence handler for ClaudeBridge MCP server.

Reads SigenEnergyManager's own files to provide historical energy analysis
without requiring InfluxDB.

Tools:
  - energy_log_days(days=7)       : raw log lines from its daily rotating logs
  - energy_daily_summary(days=14) : per-day kWh totals from daily_history.json
  - energy_compare(days_a, days_b): compare two N-day windows (e.g. this week vs last)
"""

import json
import logging
import os
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

try:
    import indigo
except ImportError:
    pass

from ..base_handler import BaseToolHandler
from ...adapters.data_provider import DataProvider

SIGEN_PLUGIN_ID = "com.clives.indigoplugin.sigenergy-energy-manager"

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


def _clamp(value: Any, default: int, lo: int, hi: int) -> int:
    try:
        return max(lo, min(int(value), hi))
    except (ValueError, TypeError):
        return default


def _daily_history_path() -> Optional[str]:
    base = indigo.server.getInstallFolderPath()
    path = os.path.join(base, "Preferences", "Plugins", SIGEN_PLUGIN_ID,
                        "daily_history.json")
    return path if os.path.isfile(path) else None


# daily_history.json field -> the name these tools have always reported.
_FIELDS = {
    "pv_kwh":          "pv_kwh",
    "grid_import_kwh": "import_kwh",
    "grid_export_kwh": "export_kwh",
    "home_kwh":        "home_kwh",
    "peak_soc":        "max_soc_pct",
    "min_soc":         "min_soc_pct",
}


def load_daily_history(path: str) -> Dict[str, Dict[str, Any]]:
    """Map date -> {pv_kwh, import_kwh, export_kwh, home_kwh, max/min_soc_pct,
    partial}. A later record for the same date replaces an earlier one."""
    with open(path, encoding="utf-8") as fh:
        raw = json.load(fh)
    out: Dict[str, Dict[str, Any]] = {}
    for rec in raw if isinstance(raw, list) else []:
        if not isinstance(rec, dict) or not rec.get("date"):
            continue
        row: Dict[str, Any] = {"date": str(rec["date"])}
        for src, dst in _FIELDS.items():
            val = rec.get(src)
            row[dst] = float(val) if isinstance(val, (int, float)) else None
        row["partial"] = bool(rec.get("energy_partial", False))
        out[row["date"]] = row
    return out


def summarise(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Sum the kWh fields that are present; never turn a missing value into 0.
    Self-sufficiency uses only days carrying both home and import figures."""
    totals: Dict[str, Any] = {}
    for key in ("pv_kwh", "import_kwh", "export_kwh", "home_kwh"):
        vals = [r[key] for r in rows if r.get(key) is not None]
        totals[key] = round(sum(vals), 2) if vals else None
    both = [r for r in rows if r.get("home_kwh") is not None and r.get("import_kwh") is not None]
    home = sum(r["home_kwh"] for r in both)
    imp  = sum(r["import_kwh"] for r in both)
    totals["self_sufficiency_pct"] = (
        round(max(0.0, min(100.0, (1 - imp / home) * 100)), 1) if home > 0 else None)
    totals["partial_days"] = sum(1 for r in rows if r.get("partial"))
    return totals


def _today_so_far() -> Optional[Dict[str, Any]]:
    """Today's running totals from the inverter device, which daily_history.json
    does not hold until midnight."""
    states = {"pvDailyKwh": "pv_kwh", "gridDailyImportKwh": "import_kwh",
              "gridDailyExportKwh": "export_kwh", "homeDailyKwh": "home_kwh"}
    try:
        for dev in indigo.devices.iter(SIGEN_PLUGIN_ID):
            if dev.deviceTypeId == "sigenergyInverter":
                out = {"date": datetime.now().date().isoformat()}
                for state, key in states.items():
                    val = dev.states.get(state)
                    out[key] = float(val) if isinstance(val, (int, float)) else None
                return out
    except Exception:
        return None
    return None


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

            try:
                days = int(days)
            except (ValueError, TypeError):
                days = 3
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
    # energy_daily_summary / energy_compare
    #
    # Both read SigenEnergyManager's own per-day record, daily_history.json,
    # written at midnight. Until 2.27.3 they parsed "[Daily]" lines out of the
    # plugin's log files — lines it has never written — so every total came
    # back null.
    # ────────────────────────────────────────────────────────────────────────

    def _history(self) -> Optional[Dict[str, Dict[str, Any]]]:
        path = _daily_history_path()
        if not path:
            return None
        return load_daily_history(path)

    def energy_daily_summary(self, days: int = 14) -> Dict[str, Any]:
        """Per-day kWh totals for the last N complete days, plus today so far."""
        self.log_incoming_request("energy_daily_summary", {"days": days})
        try:
            history = self._history()
            if history is None:
                return {"success": False,
                        "error": "SigenEnergyManager daily_history.json not found"}
            days = _clamp(days, 14, 1, 90)
            today = datetime.now().date()
            dates = [(today - timedelta(days=i)).isoformat() for i in range(days, 0, -1)]
            daily = [history[d] for d in dates if d in history]
            result = {
                "success":        True,
                "source":         "SigenEnergyManager daily_history.json",
                "days_requested": days,
                "days_found":     len(daily),
                "missing_dates":  [d for d in dates if d not in history],
                "period_totals":  summarise(daily),
                "daily":          daily,
            }
            live = _today_so_far()
            if live:
                result["today_so_far"] = live
            self.log_tool_outcome("energy_daily_summary", True, f"{len(daily)} days")
            return result
        except Exception as exc:
            return self.handle_exception(exc, "energy_daily_summary")

    def energy_compare(
        self,
        period_a_days: int = 7,
        period_b_days: int = 7,
        period_b_offset: int = 7,
    ) -> Dict[str, Any]:
        """
        Compare two periods of COMPLETE days.
        period_a = the last period_a_days days, ending yesterday
        period_b = period_b_days days, ending period_b_offset days before period_a ends

        Example: this week against last week — energy_compare(7, 7, 7)
        """
        self.log_incoming_request("energy_compare",
                                  {"period_a_days": period_a_days,
                                   "period_b_days": period_b_days,
                                   "period_b_offset": period_b_offset})
        try:
            history = self._history()
            if history is None:
                return {"success": False,
                        "error": "SigenEnergyManager daily_history.json not found"}
            period_a_days   = _clamp(period_a_days, 7, 1, 90)
            period_b_days   = _clamp(period_b_days, 7, 1, 90)
            period_b_offset = _clamp(period_b_offset, 7, 0, 365)
            yesterday = datetime.now().date() - timedelta(days=1)

            def _window(end_offset: int, n_days: int) -> Dict[str, Any]:
                end = yesterday - timedelta(days=end_offset)
                dates = [(end - timedelta(days=i)).isoformat() for i in range(n_days - 1, -1, -1)]
                rows = [history[d] for d in dates if d in history]
                return {"from": dates[0], "to": dates[-1],
                        "days_found": len(rows), **summarise(rows)}

            a = _window(0, period_a_days)
            b = _window(period_b_offset, period_b_days)

            def _diff(key):
                va, vb = a.get(key), b.get(key)
                if va is None or vb is None:
                    return {"a": va, "b": vb, "delta": None, "pct_change": None}
                delta = round(va - vb, 2)
                return {"a": va, "b": vb, "delta": delta,
                        "pct_change": round(delta / vb * 100, 1) if vb else None}

            result = {
                "success":    True,
                "source":     "SigenEnergyManager daily_history.json",
                "period_a":   {"label": f"last {period_a_days} complete days", **a},
                "period_b":   {"label": f"{period_b_days} days ending "
                                        f"{period_b_offset} days before period a", **b},
                "comparison": {k: _diff(k) for k in
                               ("pv_kwh", "import_kwh", "export_kwh", "home_kwh",
                                "self_sufficiency_pct")},
            }
            self.log_tool_outcome("energy_compare", True, "Energy period comparison complete")
            return result
        except Exception as exc:
            return self.handle_exception(exc, "energy_compare")
