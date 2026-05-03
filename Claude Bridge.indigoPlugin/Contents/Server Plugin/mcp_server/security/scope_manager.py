"""
Per-token scope management for Claude Bridge.

Indigo Web Server already authenticates the bearer token against secrets.json
before the request reaches the plugin. This module adds a *second* layer on
top: which tools is each token allowed to invoke?

Configuration file (optional):
    ~/.../Preferences/Plugins/com.clives.indigoplugin.claudebridge/scopes.json

Format (forward-compatible — fields can be omitted):
    {
        "default_scopes": ["read", "write", "admin"],
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

If the file is absent or malformed, every authenticated request gets the
``default_scopes`` (defaults to full access — backward compatible with v2.1).

Tools are classified by name into READ / WRITE / ADMIN buckets. The bucket is
matched against the token's scopes; missing scope ⇒ ScopeDenied raised.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Dict, List, Optional, Set


# ─── Tool classification ─────────────────────────────────────────────────────

# Tools that *modify* Indigo state — require 'write' or 'admin'.
WRITE_TOOLS: Set[str] = {
    # Device / variable / action mutators
    "device_turn_on", "device_turn_off", "device_set_brightness", "device_control",
    "variable_create", "variable_update",
    "action_execute_group",
    # Triggers / schedules / plugin lifecycle
    "enable_schedule", "disable_schedule",
    "enable_trigger",  "disable_trigger",
    "fire_indigo_event",
    # Memory / events
    "remember", "forget", "clear_events",
    "subscribe", "unsubscribe",
    # Plugins
    "plugin_control",
}

# Destructive / privileged operations — require 'admin'.
ADMIN_TOOLS: Set[str] = {
    "write_script", "create_script", "delete_script",
    "restart_plugin",
}

# Anything not explicitly listed defaults to READ.


def required_scope_for(tool_name: str) -> str:
    """Return the scope name required to invoke *tool_name*."""
    if tool_name in ADMIN_TOOLS:
        return "admin"
    if tool_name in WRITE_TOOLS:
        return "write"
    return "read"


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

    DEFAULT_SCOPES = ["read", "write", "admin"]

    def __init__(
        self,
        scopes_file: str,
        logger: Optional[logging.Logger] = None,
    ) -> None:
        self.scopes_file = scopes_file
        self.logger      = logger or logging.getLogger("Plugin")

        self._tokens: Dict[str, Dict] = {}
        self._default: List[str]      = list(self.DEFAULT_SCOPES)
        self.reload()

    def reload(self) -> bool:
        """Re-read scopes.json. Returns True on success, False if missing/invalid."""
        if not os.path.isfile(self.scopes_file):
            self._tokens  = {}
            self._default = list(self.DEFAULT_SCOPES)
            return False
        try:
            with open(self.scopes_file, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            if not isinstance(data, dict):
                raise ValueError("scopes.json must be a JSON object")
            self._default = list(data.get("default_scopes") or self.DEFAULT_SCOPES)
            tokens_raw    = data.get("tokens") or {}
            if not isinstance(tokens_raw, dict):
                raise ValueError("'tokens' must be an object keyed by bearer token")
            self._tokens = {
                token: {
                    "name":   info.get("name") or "",
                    "scopes": list(info.get("scopes") or self._default),
                }
                for token, info in tokens_raw.items()
                if isinstance(info, dict)
            }
            self.logger.info(
                f"\t✅ ScopeManager loaded {len(self._tokens)} token(s); "
                f"default={self._default}"
            )
            return True
        except Exception as e:
            self.logger.warning(
                f"\t⚠️  scopes.json invalid ({e}); falling back to default {self.DEFAULT_SCOPES}"
            )
            self._tokens  = {}
            self._default = list(self.DEFAULT_SCOPES)
            return False

    # ── Lookup ────────────────────────────────────────────────────────────

    def scopes_for_token(self, bearer: Optional[str]) -> Set[str]:
        """
        Return the scope set for the given bearer token. Unknown / missing
        tokens fall back to *default_scopes* (full access in stock config) —
        this preserves backward compatibility with v2.1 deployments.
        """
        if not bearer:
            return set(self._default)
        info = self._tokens.get(bearer)
        if info is None:
            return set(self._default)
        return set(info.get("scopes") or self._default)

    def name_for_token(self, bearer: Optional[str]) -> str:
        """Friendly label for a bearer token, used in logs/health snapshots."""
        if not bearer:
            return "anonymous"
        info = self._tokens.get(bearer)
        return (info or {}).get("name") or "unregistered"

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
            "tokens_configured": len(self._tokens),
            "default_scopes":    list(self._default),
            "names": [
                {"name": info["name"] or "unnamed", "scopes": info["scopes"]}
                for info in self._tokens.values()
            ],
        }
