#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    server.py
# Description: Server-wide reads — the house status, energy history, server
#              facts, the event log, control pages, health and raw requests.
# Author:      CliveS & Claude Opus 5.5
# Date:        23-09-2026
# Version:     1.0

from typing import Any, Dict

from ..registry import tool
from ._schema import (bad_choice, boolean, coerce_bool, enum, id_or_name, number, refuse,
                      string, unused_args)

_REPORT_SECTIONS = ["energy", "heating", "security", "devices", "alerts", "automation"]
_HOME_SECTIONS = ("summary", "energy", "heating", "security", "report")


@tool("home_status", scope="read", cacheable=True, reads={"device", "variable"},
      description=(
          "The state of the house. section='summary' (default): every device grouped by type, "
          "key variable values, energy status, active alerts (errors, low battery) and "
          "automation counts. 'energy': a live SigenEnergyManager snapshot — battery SOC, "
          "solar, grid import/export, tariff. 'heating': every thermostat/TRV with setpoints, "
          "temperatures and zone modes. 'security': open doors and windows, active motion, "
          "leak/smoke/CO alerts. 'report': a markdown prose report to show the user as it "
          "stands; report_sections picks sections (energy, heating, security, devices, alerts, "
          "automation), default all."),
      properties={
          "section": enum(_HOME_SECTIONS, "Which view (default summary)"),
          "report_sections": {"type": "array",
                              "items": {"type": "string", "enum": _REPORT_SECTIONS},
                              "description": "section='report' only: sections to include "
                                             "(omit for all)"},
      })
def home_status(ctx, section="summary", report_sections=None):
    if section not in _HOME_SECTIONS:
        return bad_choice("section", section, _HOME_SECTIONS)
    if report_sections is not None and section != "report":
        return refuse("home_status: report_sections applies only to section='report'")
    hs = ctx.home_status_handler
    if section == "summary":
        return hs.home_status()
    if section == "report":
        return hs.home_status_report(report_sections)
    return getattr(hs, f"{section}_status")()


@tool("energy_history", scope="read", cacheable=True, reads={"external"},
      description=(
          "Per-day kWh totals from SigenEnergyManager's own daily record: PV generated, grid "
          "imported, grid exported, home consumption, max/min SOC and self-sufficiency, over "
          "the last `days` complete days (default 14, max 90), with today's running totals as "
          "today_so_far. compare=true instead sets those days against an equally long earlier "
          "period ending compare_offset_days before them (default: the period just before) "
          "and returns kWh deltas and percentage changes."),
      properties={
          "days": number("Complete days to cover (default 14, max 90)"),
          "compare": boolean("Compare with an earlier period instead (default false)"),
          "compare_offset_days": number("compare=true only: how many days before the recent "
                                        "period ends the earlier one ends (default = days)"),
      })
def energy_history(ctx, days=14, compare=False, compare_offset_days=None):
    et = ctx.energy_tools_handler
    if not coerce_bool(compare):
        if compare_offset_days is not None:
            return refuse("energy_history: compare_offset_days applies only with compare=true")
        return et.energy_daily_summary(days)
    offset = days if compare_offset_days is None else compare_offset_days
    return et.energy_compare(days, days, offset)


@tool("server_info", scope="read",
      description=(
          "Facts about this Indigo server in one reply: install, Logs and database paths "
          "(to find the history DB and logs without typing a version number), the local web "
          "server URL, the Reflector's URL and connection status (url is null when no "
          "Reflector is active), the configured latitude/longitude, and sunrise and sunset "
          "for date_iso (YYYY-MM-DD, default today)."),
      properties={"date_iso": string("Optional YYYY-MM-DD for sunrise/sunset (default today)")})
def server_info(ctx, date_iso=None):
    st, ext = ctx.system_tools_handler, ctx.extended_tools_handler
    reply: Dict[str, Any] = {"success": True}
    errors: Dict[str, str] = {}

    def _part(label, result, *keys):
        if not isinstance(result, dict) or result.get("success") is False:
            errors[label] = (result or {}).get("error", "unavailable") \
                if isinstance(result, dict) else str(result)
            return None
        if len(keys) == 1:
            return result.get(keys[0])
        return {k: result.get(k) for k in keys}

    reply["paths"] = _part("paths", st.get_indigo_paths(), "paths")
    reply["web_server_url"] = _part("web_server_url", ext.get_web_server_url(), "url") or None
    url = _part("reflector_url", st.get_reflector_url(), "url")
    # getReflectorURL() hands back None, not "", when the Reflector is off.
    reply["reflector"] = {"url": url or None,
                          "status": _part("reflector_status", st.get_reflector_status(),
                                          "status")}
    reply["location"] = _part("location", ext.get_latitude_longitude(), "latitude", "longitude")
    rise = ext.calculate_sunrise(date_iso)
    reply["sun"] = {"date": rise.get("date", date_iso) if isinstance(rise, dict) else date_iso,
                    "sunrise": _part("sunrise", rise, "sunrise"),
                    "sunset": _part("sunset", ext.calculate_sunset(date_iso), "sunset")}
    if errors:
        reply["errors"] = errors
    return reply


@tool("system_health", scope="read", cacheable=True, reads={"external"},
      description=("Return a snapshot of Mac Mini system health: macOS version, Python version, "
                   "disk usage (total/used/free/%), RAM summary, and uptime. No parameters "
                   "required."))
def system_health(ctx):
    return ctx.system_tools_handler.system_health()


@tool("query_event_log", scope="read",
      description=(
          "Query Indigo server event log entries. Without after/before returns the most recent "
          "line_count entries. With after/before reads from the on-disk log files and returns "
          "all entries in that time window (useful for investigating past events). Time "
          "formats: 'HH:MM:SS' (today assumed), 'YYYY-MM-DDTHH:MM:SS' (full). The file scan "
          "covers at most 14 days, anchored on the END of the range: 'before' with no 'after' "
          "searches the 14 days leading up to it. The 'range' block in the reply reports the "
          "window actually scanned and sets span_clamped when the request was wider — so an "
          "empty result is never ambiguous. An inverted range (after >= before) is rejected, "
          "not answered with an empty list."),
      properties={
          "line_count": number("Max entries to return (default: 20)"),
          "show_timestamp": boolean("Include timestamps in entries (default: true)"),
          "after": string("Return only entries after this time. Format: 'HH:MM:SS' for today, "
                          "or 'YYYY-MM-DDTHH:MM:SS' for a specific date. Example: '07:45:00'"),
          "before": string("Return only entries before this time. Format: 'HH:MM:SS' for today, "
                           "or 'YYYY-MM-DDTHH:MM:SS'. Example: '07:52:00'"),
      })
def query_event_log(ctx, line_count=20, show_timestamp=True, after=None, before=None):
    return ctx.log_query_handler.query(line_count=line_count, show_timestamp=show_timestamp,
                                       after=after, before=before)


@tool("control_pages", scope="read",
      description=("Without page_id, list every control page (id, name, folder and so on). With "
                   "page_id, one page's properties AND its full layout: every element with its "
                   "type, position, size, caption, and the device/variable/action group it points "
                   "at. Elements whose target no longer exists are flagged, so this finds "
                   "controls left behind by a deleted device."),
      properties={"page_id": id_or_name("Optional control page id")})
def control_pages(ctx, page_id=None):
    ext = ctx.extended_tools_handler
    return ext.list_control_pages() if page_id is None else ext.get_control_page(page_id)


@tool("raw_server_request", scope="admin",
      description=("Send a READ-ONLY raw named request to the Indigo server "
                   "(indigo.rawServerRequest). Undocumented internal API — unsupported and may "
                   "change between Indigo versions. Only 'Get*' request names are permitted; "
                   "mutating raw commands are not reachable. Example: name='GetControlPage', "
                   "args={'ID': 12345, 'GetPageFlags': 65536}. Use 65536, NOT Indigo's own "
                   "FULL_PAGE_FLAGS (65538) — its second flag is ignore_actions, so 65538 "
                   "withholds every element's action and a page of working buttons reads as if "
                   "nothing on it does anything. ADMIN scope: classified by what it can reach, "
                   "not by today's Get-only guard."),
      properties={"name": string("Request name, must begin with 'Get'"),
                  "args": {"type": "object", "description": "Optional arguments for the request"}},
      required=["name"])
def raw_server_request(ctx, name, args=None):
    return ctx.system_tools_handler.raw_server_request(name, args)


# ── Audits ───────────────────────────────────────────────────────────────────

_AUDITS = {
    "home":                 ((), "audit_handler", "audit_home"),
    "errors":               ((), "audit_handler", "find_devices_in_error"),
    "low_battery":          (("threshold",), "audit_handler", "find_low_battery"),
    "stale":                (("days",), "audit_handler", "find_stale_devices"),
    "variables":            ((), "audit_handler", "audit_variables"),
    "conflicts":            ((), "audit_handler", "find_conflicts"),
    "orphaned_scripts":     ((), "system_tools_handler", "find_orphaned_scripts"),
    "orphaned_plugin_data": ((), "system_tools_handler", "find_orphaned_plugin_data"),
    "deprecated":           (("include_warnings",), "extended_tools_handler",
                             "get_deprecated_elements"),
    "api_coverage":         ((), "system_tools_handler", "audit_api_coverage"),
    "large_files":          (("path", "min_mb", "max_results"), "system_tools_handler",
                             "find_large_files"),
}


@tool("audit", scope="read", cacheable=True,
      reads={"device", "variable", "script", "external"},
      description=(
          "Run one health check, chosen by check. home: the overview — devices in error, low "
          "battery, stale devices, empty variables, disabled triggers and schedules, "
          "automation counts. errors: devices in an error or fault state. low_battery: "
          "battery below threshold % (default 20), lowest first. stale: enabled devices "
          "unchanged for more than days (default 7). variables: variables no script "
          "references, and empty/None/'null' values. conflicts: duplicate device or trigger "
          "names, devices sharing a hardware address, scripts naming deleted ids, several "
          "scripts writing one variable. orphaned_scripts: scripts referencing device or "
          "variable ids that no longer exist. orphaned_plugin_data: prefs folders, .indiPref "
          "files and LaunchAgents left by uninstalled plugins — read a prefs file before "
          "deleting it, credentials have been found in them. deprecated: Indigo's deprecated "
          "objects (include_warnings adds warning-level ones). api_coverage: the live indigo.* "
          "namespaces against the frozen baseline, after an Indigo upgrade. large_files: files "
          "of at least min_mb MB (default 10) under path (default the Indigo install folder), "
          "largest first, up to max_results (default 50)."),
      properties={
          "check": enum(list(_AUDITS), "Which check to run"),
          "threshold": number("low_battery: battery % threshold (default 20)"),
          "days": number("stale: inactivity threshold in days (default 7)"),
          "include_warnings": boolean("deprecated: also list warning-level items"),
          "path": string("large_files: directory to scan (default the install folder)"),
          "min_mb": number("large_files: minimum size in MB (default 10)"),
          "max_results": number("large_files: most files to return (default 50)"),
      },
      required=["check"])
def audit(ctx, check, threshold=None, days=None, include_warnings=None, path=None,
          min_mb=None, max_results=None):
    if check not in _AUDITS:
        return bad_choice("check", check, _AUDITS)
    given = {"threshold": threshold, "days": days, "include_warnings": include_warnings,
             "path": path, "min_mb": min_mb, "max_results": max_results}
    allowed, handler_name, method = _AUDITS[check]
    stray = unused_args("audit", check, given, allowed)
    if stray:
        return stray
    kwargs = {k: given[k] for k in allowed if given[k] is not None}
    return getattr(getattr(ctx, handler_name), method)(**kwargs)
