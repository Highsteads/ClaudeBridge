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

Each built-in tool declares its scope (read / write / admin) in the tool
registry (mcp_server/registry.py); it is matched against the token's scopes and
a missing scope raises ScopeDenied. Anything not in the registry and not a
classified plugin-provided tool fails closed to admin.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Dict, List, Optional, Set


# ─── Tool classification ─────────────────────────────────────────────────────
#
# Every built-in tool declares its scope where it is defined (mcp_server/
# toolsets/, via the @tool decorator in mcp_server/registry.py). Nothing is
# listed here by hand any more: until 3.0 these were three literal sets kept in
# step with the handler, and a tool missing from all three failed closed to
# admin with only a startup log line to say so.
#
#   read  — pure queries, no state change
#   write — modify Indigo state
#   admin — destructive, irreversible, code execution, plugin lifecycle,
#           physical security, and data leaving the house
#
# READ_TOOLS / WRITE_TOOLS / ADMIN_TOOLS remain importable names (derived on
# access, see __getattr__ below) for anything that reads them.

_SCOPE_SETS = {"READ_TOOLS": "read", "WRITE_TOOLS": "write", "ADMIN_TOOLS": "admin"}


def __getattr__(name: str):
    if name in _SCOPE_SETS:
        from .. import registry
        return set(registry.names_in_scope(_SCOPE_SETS[name]))
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def _registry_scope(tool_name: str) -> Optional[str]:
    from .. import registry
    spec = registry.spec_for(tool_name)
    return spec.scope if spec is not None else None


# Plugin-provided tools (v2.26.0). They are registered at runtime from other
# plugins' manifests, so they cannot appear in the static sets above. Each is
# classified when it is registered — "read" or "write" from its manifest's
# write flag, never "admin", because the provider decided what it does — and
# the audit counts them as classified. A name in this map that also appears
# in a static set is impossible by construction (the manager skips names that
# collide with built-ins), and the static sets win if it ever happens.
_DYNAMIC_SCOPES: Dict[str, str] = {}
_DYNAMIC_ALLOWED = ("read", "write")


def register_dynamic_scope(tool_name: str, scope: str) -> None:
    """Classify a runtime-registered tool. Anything but read/write fails
    closed to admin — a provider cannot grant itself a lower bar than the
    manifest allows, and a typo must not open a write to a read token."""
    _DYNAMIC_SCOPES[tool_name] = scope if scope in _DYNAMIC_ALLOWED else "admin"


def unregister_dynamic_scopes(tool_names) -> None:
    for name in list(tool_names or ()):
        _DYNAMIC_SCOPES.pop(name, None)


def dynamic_scope_names() -> Set[str]:
    return set(_DYNAMIC_SCOPES)


def required_scope_for(tool_name: str) -> str:
    """Return the scope name required to invoke *tool_name* (fail-closed).

    The registry wins over a dynamic (plugin-provided) classification — the
    external-tool manager already refuses a name that collides with a built-in.
    """
    scope = _registry_scope(tool_name)
    if scope is not None:
        return scope
    if tool_name in _DYNAMIC_SCOPES:
        return _DYNAMIC_SCOPES[tool_name]
    # Unknown — fail closed, so nothing can reach a read/write token until it
    # is declared somewhere that classifies it.
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

    def _coerce_scopes(self, raw, where: str) -> List[str]:
        """Turn a scopes value from the file into a clean list of scope names.

        `list("admin")` gives ['a','d','m','i','n'] — five scopes, none of them
        real — so a user who writes `"scopes": "admin"` instead of
        `["admin"]` gets a token with NO usable permissions and no explanation.
        A bare string is accepted as the single scope it obviously means, and
        anything else is rejected loudly rather than silently mangled.
        """
        if isinstance(raw, str):
            self.logger.warning(
                f"\tscopes.json: {where} is the string {raw!r}; reading it as "
                f'["{raw}"]. Use a JSON list to silence this.'
            )
            return [raw]
        if isinstance(raw, (list, tuple, set)):
            return [str(s) for s in raw]
        raise ValueError(f"{where}: scopes must be a list of scope names, "
                         f"got {type(raw).__name__}")

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
        # The file is keyed by full bearer tokens, so re-assert 0600 on every load.
        # A copy restored from a backup, or one created before this was enforced,
        # otherwise sits group/world readable for the life of the install. Same
        # pattern as SubscriptionStore.load() for webhooks.json.
        try:
            if (os.stat(self.scopes_file).st_mode & 0o077) != 0:
                os.chmod(self.scopes_file, 0o600)
                self.logger.warning(
                    "\tscopes.json was readable by other users — permissions "
                    "tightened to 0600. It holds your bearer tokens."
                )
        except Exception as exc:
            self.logger.warning(f"\tCould not check/repair scopes.json permissions: {exc}")
        try:
            with open(self.scopes_file, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            if not isinstance(data, dict):
                raise ValueError("scopes.json must be a JSON object")
            default_raw = data.get("default_scopes")
            self._default_explicit = default_raw is not None
            self._default = (self._coerce_scopes(default_raw, "default_scopes")
                             if default_raw is not None else list(self.DEFAULT_SCOPES))
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
                scopes = (self._coerce_scopes(raw_scopes, f"token {token[:8]}…")
                          if raw_scopes is not None else list(self._default))
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
        Verify every registered tool is classified. A registry tool always is;
        a plugin-provided one is classified when it registers. Anything else in
        the list is unclassified, logged as an ERROR, and fails closed to admin.
        Returns a report.
        """
        from .. import registry
        names = set(tool_names or [])
        built_in = set(registry.load())
        dynamic = names & dynamic_scope_names()
        unclassified = sorted(names - built_in - dynamic)
        stale = sorted(built_in - names)   # declared but not registered on this handler
        if unclassified:
            self.logger.error(
                f"\tScope classification GAP — {len(unclassified)} registered tool(s) "
                f"are unclassified and will require ADMIN: {unclassified}"
            )
        if stale:
            self.logger.debug(f"\tScope classification: declared-but-not-registered: {stale}")
        if not unclassified:
            counts = {sc: len(names & registry.names_in_scope(sc)) for sc in ("read", "write", "admin")}
            self.logger.info(
                f"\tScope classification OK — {len(names)} tools "
                f"(read={counts['read']}, write={counts['write']}, admin={counts['admin']}"
                + (f", plugin-provided={len(dynamic)}" if dynamic else "") + ")"
            )
        return {"unclassified": unclassified, "multi_classified": [], "stale": stale}

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
