"""
Per-token scope management for Claude Bridge.

Indigo Web Server already authenticates the bearer token against secrets.json
before the request reaches the plugin. This module adds a *second* layer on
top: which tools is each token allowed to invoke?

Configuration file (optional):
    ~/.../Preferences/Plugins/com.clives.indigoplugin.claudebridge/scopes.json

Format (forward-compatible — fields can be omitted):
    {
        "default_scopes": ["read"],
        "tokens": {
            "<bearer-token>": {
                "name":   "claude-code",
                "scopes": ["read", "write", "admin"]
            },
            "<other-token>": {
                "name":   "phone-app",
                "scopes": ["read"]
            }
        }
    }

Behaviour (revised 06-Jun-2026 — fail-closed once configured):
    * If NO scopes.json exists at all, the plugin is in the stock single-token
      state: every authenticated token gets full access (read+write+admin) and
      a one-line WARNING is logged so the operator knows the second layer is
      open. This preserves backward compatibility — the IWS bearer token is
      still the gate.
    * If scopes.json EXISTS (the operator has opted into scoping) the gate is
      enforced strictly:
        - a token listed in "tokens" gets exactly its scopes (an explicit
          empty list ``[]`` means deny-all, not "fall back to default");
        - a token NOT listed gets "default_scopes" only if that key was
          explicitly provided, otherwise it is denied;
        - a malformed/unreadable file never silently widens access — a prior
          good config is kept, and a broken first load degrades to read-only
          with an ERROR (not to full admin).

Tools are classified by name into READ / WRITE / ADMIN buckets below. The
bucket is matched against the token's scopes; missing scope ⇒ ScopeDenied.
The three buckets are an exhaustive, deny-by-default partition of every
registered tool — see audit_classification(), called once at startup, which
logs an ERROR if any registered tool is unclassified so a newly-added tool can
never silently fall into READ.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Dict, List, Optional, Set


# ─── Tool classification ─────────────────────────────────────────────────────
#
# DENY-BY-DEFAULT: every registered tool MUST appear in exactly one of the three
# sets below. required_scope_for() returns 'admin' for anything unlisted (the
# safest fail-closed default) and audit_classification() logs an ERROR at
# startup for any registered tool missing from all three sets.

# Pure queries — no state change. Require 'read'.
READ_TOOLS: Set[str] = {
    "search_entities", "get_devices_by_type", "get_device_by_id", "get_device_by_name",
    "get_devices_by_state", "list_devices", "list_variables", "list_schedules",
    "list_triggers", "list_action_groups", "list_control_pages", "list_plugins",
    "list_python_scripts", "list_script_backups", "list_subscriptions", "list_variable_folders",
    "get_variable_by_id", "get_action_group_by_id", "get_control_page", "get_plugin_by_id",
    "get_plugin_status", "home_status", "home_status_report", "heating_status", "energy_status",
    "energy_compare", "energy_daily_summary", "energy_log_days", "analyze_historical_data",
    "device_history", "audit_home", "audit_variables", "find_conflicts", "find_devices_in_error",
    "find_low_battery", "find_orphaned_plugin_data", "find_orphaned_scripts", "find_stale_devices",
    "find_large_files", "dependency_map", "action_group_get_dependencies", "schedule_get_dependencies",
    "get_deprecated_elements", "get_latitude_longitude", "get_reflector_url", "get_web_server_url",
    "calculate_sunrise", "calculate_sunset", "check_plugin_updates", "read_script", "recall",
    "recall_topics", "get_events", "query_event_log", "security_status", "system_health",
    "plugin_diff_source_vs_installed", "plugin_lint", "plugin_node_check_html",
    "plugin_show_packages_versions", "plugin_validate_xml",
    # v2.9.0 — read-only API drift detector
    "audit_api_coverage",
}

# Tools that *modify* Indigo state — require 'write' or 'admin'.
WRITE_TOOLS: Set[str] = {
    # Device / dimmer / climate / fan / speed / sprinkler mutators
    "device_turn_on", "device_turn_off", "device_set_brightness", "device_control", "device_toggle",
    "dimmer_brighten_by", "dimmer_dim_by",
    "set_heat_setpoint", "set_cool_setpoint", "set_hvac_mode",
    "increase_heat_setpoint", "decrease_heat_setpoint",
    "set_color", "set_fan_mode", "set_fan_speed",
    "speedcontrol_decrease", "speedcontrol_increase", "speedcontrol_set_index",
    "sprinkler_next_zone", "sprinkler_pause", "sprinkler_previous_zone", "sprinkler_resume",
    "sprinkler_run", "sprinkler_set_zone", "sprinkler_stop",
    # Variables
    "variable_create", "variable_update", "variable_move_to_folder",
    # Action groups / schedules / triggers
    "action_execute_group",
    "enable_schedule", "disable_schedule", "execute_schedule_now", "schedule_remove_delayed_actions",
    "enable_trigger", "disable_trigger",
    "fire_indigo_event", "fire_trigger",
    "enable_action_group", "disable_action_group", "duplicate_action_group",
    # Folders / device housekeeping
    "create_device_folder", "create_variable_folder",
    "enable_device", "rename_device", "move_device_to_folder", "move_trigger_to_folder",
    "duplicate_device", "duplicate_schedule", "request_status_update",
    # Memory / events / subscriptions / logging
    "remember", "forget", "clear_events", "subscribe", "unsubscribe", "log_message",
    # Outbound side effects (send as the user)
    "send_email", "send_notification", "server_speak",
    # v2.9.0 — diagnostics, energy reset, delayed actions, native broadcasts.
    # The broadcasts are WRITE not ADMIN: reversible mass on/off, same class of
    # effect as action_execute_group.
    "beep_device", "ping_device", "reset_energy_accumulator",
    "device_remove_delayed_actions",
    "all_lights_off", "all_lights_on", "all_devices_off",
}

# Destructive / irreversible / code-execution / lifecycle / physical-security — require 'admin'.
ADMIN_TOOLS: Set[str] = {
    # Arbitrary code / GUI scripting / script files
    "execute_indigo_python", "execute_plugin_menu_item", "run_script", "scaffold_automation_script",
    "write_script", "create_script", "delete_script",
    # Plugin lifecycle
    "restart_plugin", "plugin_refresh_deps",
    # Irreversible deletes
    "delete_device", "delete_schedule", "delete_trigger", "delete_action_group", "variable_delete",
    "remove_all_delayed_actions",
    "delete_device_folder", "delete_variable_folder",   # v2.9.0 — can cascade-delete contents
    # Physical security
    "lock_device", "unlock_device",
    # Outbound webhooks — registering an egress target POSTs home state to an
    # external URL, strictly more sensitive than a WRITE (data-leaving-the-house).
    "webhook_create", "webhook_list", "webhook_delete",
}

# Order matters: a name should never be in more than one set (audit enforces it),
# but if it somehow is, the higher privilege wins.
def required_scope_for(tool_name: str) -> str:
    """Return the scope name required to invoke *tool_name* (fail-closed)."""
    if tool_name in ADMIN_TOOLS:
        return "admin"
    if tool_name in WRITE_TOOLS:
        return "write"
    if tool_name in READ_TOOLS:
        return "read"
    # Unclassified — fail closed. audit_classification() will have logged an
    # ERROR for this at startup; require admin so a new tool can never be
    # reachable by a read/write token until it is explicitly classified.
    return "admin"


# ─── Errors ──────────────────────────────────────────────────────────────────

class ScopeDenied(Exception):
    """Raised when a token lacks the scope needed to call a tool."""

    def __init__(self, tool: str, required: str, granted: Set[str]):
        self.tool     = tool
        self.required = required
        self.granted  = sorted(granted)
        super().__init__(
            f"Tool '{tool}' requires scope '{required}'; "
            f"token has {self.granted or ['<none>']}"
        )


# ─── Manager ─────────────────────────────────────────────────────────────────

class ScopeManager:
    """
    Loads and queries the scopes.json file. Reload-friendly — call ``reload()``
    after editing the file to pick up changes without restarting the plugin.
    """

    # Scopes granted when NO scopes.json exists (stock single-token install).
    DEFAULT_SCOPES = ["read", "write", "admin"]
    # Scopes a broken-on-first-load scopes.json degrades to (functional but
    # cannot mutate — forces the operator to fix the JSON, never opens admin).
    SAFE_FALLBACK_SCOPES = ["read"]

    def __init__(
        self,
        scopes_file: str,
        logger: Optional[logging.Logger] = None,
    ) -> None:
        self.scopes_file = scopes_file
        self.logger      = logger or logging.getLogger("Plugin")

        self._tokens: Dict[str, Dict] = {}
        self._default: List[str]      = list(self.DEFAULT_SCOPES)
        self._configured: bool        = False   # True once a scopes.json has loaded OK
        self._default_explicit: bool  = False   # True if the file set default_scopes
        self._ever_loaded_ok: bool    = False   # True once any valid load has happened
        self.reload()

    def reload(self) -> bool:
        """Re-read scopes.json. Returns True on success, False if missing/invalid."""
        # No file at all → stock unconfigured state: permissive, but warn so the
        # operator knows the second layer is open.
        if not self.scopes_file or not os.path.isfile(self.scopes_file):
            self._tokens          = {}
            self._default         = list(self.DEFAULT_SCOPES)
            self._configured      = False
            self._default_explicit = False
            # INFO not WARNING: single-token + IWS-gated is the intended stock
            # state, not a misconfiguration. The note just tells an operator how
            # to opt into per-token scoping if they want it.
            self.logger.info(
                "\tscopes.json not present — all IWS-authenticated tokens have full access. "
                "Create scopes.json to restrict per-token scopes (optional)."
            )
            return False
        try:
            with open(self.scopes_file, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            if not isinstance(data, dict):
                raise ValueError("scopes.json must be a JSON object")
            default_raw = data.get("default_scopes")
            self._default_explicit = default_raw is not None
            self._default = list(default_raw) if default_raw is not None else list(self.DEFAULT_SCOPES)
            tokens_raw    = data.get("tokens") or {}
            if not isinstance(tokens_raw, dict):
                raise ValueError("'tokens' must be an object keyed by bearer token")
            new_tokens = {}
            for token, info in tokens_raw.items():
                if not isinstance(info, dict):
                    continue
                raw_scopes = info.get("scopes")
                # Distinguish "key absent" (inherit default) from "explicit []"
                # (deny-all). `raw or default` would wrongly treat [] as falsy.
                scopes = list(raw_scopes) if raw_scopes is not None else list(self._default)
                new_tokens[token] = {"name": info.get("name") or "", "scopes": scopes}
            self._tokens     = new_tokens
            self._configured = True
            self._ever_loaded_ok = True
            self.logger.info(
                f"\tScopeManager loaded {len(self._tokens)} token(s); "
                f"default={self._default if self._default_explicit else '(deny unknown tokens)'}"
            )
            return True
        except Exception as e:
            # NEVER widen access on a parse error. Keep a prior good config if we
            # have one; otherwise degrade to read-only (functional, no mutation)
            # and shout at ERROR so the operator fixes the file.
            if self._ever_loaded_ok:
                self.logger.error(
                    f"\tscopes.json invalid ({e}) — KEEPING the previously loaded scopes; "
                    f"fix the file and reload."
                )
            else:
                self._tokens           = {}
                self._default          = list(self.SAFE_FALLBACK_SCOPES)
                self._configured       = True
                self._default_explicit = True
                self.logger.error(
                    f"\tscopes.json invalid ({e}) — failing CLOSED to read-only for all tokens "
                    f"until the file is valid. No token can mutate state."
                )
            return False

    # ── Classification audit (startup self-check) ──────────────────────────

    def audit_classification(self, tool_names) -> Dict[str, List[str]]:
        """
        Verify every registered tool is classified into exactly one bucket.
        Logs an ERROR for any unclassified tool (which fails closed to 'admin')
        and a WARNING for any name in more than one bucket. Returns a report.
        """
        names = set(tool_names or [])
        union = READ_TOOLS | WRITE_TOOLS | ADMIN_TOOLS
        unclassified = sorted(names - union)
        multi = sorted(
            n for n in names
            if (n in READ_TOOLS) + (n in WRITE_TOOLS) + (n in ADMIN_TOOLS) > 1
        )
        stale = sorted(union - names)   # classified but not registered
        if unclassified:
            self.logger.error(
                f"\tScope classification GAP — {len(unclassified)} registered tool(s) "
                f"are unclassified and will require ADMIN: {unclassified}"
            )
        if multi:
            self.logger.warning(f"\tScope classification: tool(s) in multiple buckets: {multi}")
        if stale:
            self.logger.debug(f"\tScope classification: classified-but-not-registered: {stale}")
        if not unclassified and not multi:
            self.logger.info(
                f"\tScope classification OK — {len(names)} tools "
                f"(read={len(READ_TOOLS & names)}, write={len(WRITE_TOOLS & names)}, "
                f"admin={len(ADMIN_TOOLS & names)})"
            )
        return {"unclassified": unclassified, "multi_classified": multi, "stale": stale}

    # ── Lookup ────────────────────────────────────────────────────────────

    def scopes_for_token(self, bearer: Optional[str]) -> Set[str]:
        """
        Return the scope set for the given bearer token.

        Unconfigured (no scopes.json): full DEFAULT_SCOPES — backward compatible.
        Configured: a listed token gets its own scopes (explicit [] = none); an
        unlisted token gets default_scopes only if it was set explicitly, else
        an empty set (deny).
        """
        if not self._configured:
            return set(self._default)
        if not bearer:
            return set()
        info = self._tokens.get(bearer)
        if info is not None:
            return set(info.get("scopes") or [])
        # Unknown token under a configured file: only the explicit default grants.
        return set(self._default) if self._default_explicit else set()

    def name_for_token(self, bearer: Optional[str]) -> str:
        """Friendly label for a bearer token, used in logs/health snapshots."""
        if not bearer:
            return "anonymous"
        info = self._tokens.get(bearer)
        if info is None:
            return "unregistered" if self._configured else "default"
        return info.get("name") or "unregistered"

    def check(self, bearer: Optional[str], tool_name: str) -> Set[str]:
        """
        Raise :class:`ScopeDenied` if the token lacks the scope for *tool_name*.
        Returns the resolved scope set (so callers can log/cache it).
        """
        scopes   = self.scopes_for_token(bearer)
        required = required_scope_for(tool_name)
        if required not in scopes:
            raise ScopeDenied(tool_name, required, scopes)
        return scopes

    def summary(self) -> Dict:
        """Health-endpoint summary — never exposes the token strings."""
        return {
            "configured":        self._configured,
            "tokens_configured": len(self._tokens),
            "default_scopes":    list(self._default) if (self._default_explicit or not self._configured) else [],
            "names": [
                {"name": info["name"] or "unnamed", "scopes": info["scopes"]}
                for info in self._tokens.values()
            ],
        }
