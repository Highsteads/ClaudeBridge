#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    delete_gate.py
# Description: Second, operation-specific brake on the deletes that cannot be
#              undone — a default-off preference PLUS an explicit per-call
#              confirmation, on top of the admin scope.
# Author:      CliveS & Claude Opus 5
# Date:        29-08-2026
# Version:     1.0

"""
Two independent conditions before an irreversible delete runs.

Admin scope alone was the only brake until v2.24.0, and it is the wrong shape
for this: a token is granted admin so it can write scripts and restart plugins,
and that same grant silently carried the power to delete a trigger in one call
with nothing else in the way. Scope answers "may this caller do admin things";
it cannot answer "did anyone mean to destroy this particular object".

So there are three boundaries now, and they fail independently:

  1. admin scope        — is this caller trusted at all
  2. a plugin preference (DEFAULT OFF) — has the owner of this house enabled
     deletion for AI callers, ever
  3. `confirm: true` on the call — did this specific request mean it

Only the deletes with NO recovery path are gated. `delete_script` is not here
on purpose: it ARCHIVES to `_backups/_archived/` and can be recovered, so
gating it would add friction to routine development for no safety gain. If a
tool gains or loses a recovery path, move it in or out of this set rather than
adding a special case at the call site.
"""

from typing import Any, Dict, Optional

from .. import runtime_config

# Which tools are gated is declared on each tool (destructive=True in its
# @tool decorator, mcp_server/registry.py): delete_device, variable_delete,
# delete_automation and delete_folder. Folder deletes are included because they
# can cascade into their contents, which is strictly worse than one object.
# One action of a multi-action tool can be gated on its own
# (destructive_actions): zwave's enter_exclusion removes hardware from the
# Z-Wave network, and re-including it means pairing it again by hand.
# DESTRUCTIVE_TOOLS stays importable, derived on access.


def __getattr__(name: str):
    if name == "DESTRUCTIVE_TOOLS":
        from .. import registry
        return set(registry.destructive_names())
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def is_gated(tool_name: str, tool_args: Optional[Dict[str, Any]] = None) -> bool:
    """True if this call must pass the gate. With no arguments, whether the
    whole tool is gated; with them, also whether the chosen action is (zwave's
    enter_exclusion, which removes hardware from the network)."""
    from .. import registry
    spec = registry.spec_for(tool_name)
    if spec is None:
        return False
    if tool_args is None:
        return spec.destructive
    return spec.is_destructive_call(tool_args)


# The pluginPrefs key and the label a user sees, kept together so an error
# message can tell someone exactly which checkbox to tick.
PREFERENCE_KEY   = "allow_destructive_delete"
PREFERENCE_LABEL = "Allow Claude to delete devices, variables and automations"


# The wording appended to every gated tool's description, and the description
# of the argument itself. The registry adds both when a tool is declared
# destructive, so the live schema and the generated docs/tools.md carry the
# same words from the same place.
CONFIRM_DESCRIPTION_SUFFIX = (
    " Requires confirm=true AND the plugin's delete preference to be enabled."
)
CONFIRM_ARG_DESCRIPTION = (
    "Must be true. This delete cannot be undone, and it is also refused unless "
    "the user has enabled deletion in the plugin preferences."
)


class DeleteDenied(Exception):
    """Raised when a gated delete is missing the preference, the confirm, or both."""


def is_enabled() -> bool:
    """Whether the owner has enabled AI deletion at all.

    NOT `bool()`: Indigo re-serialises a checkbox as the STRING "false" after a
    Configure dialog save, and `bool("false")` is True — which would turn the
    feature ON for precisely the people who had turned it off and saved. Same
    trap that made the old InfluxDB switch read backwards in v2.20.2.
    """
    return runtime_config.get_bool(PREFERENCE_KEY, False)


def check(tool_name: str, tool_args: Dict[str, Any]) -> None:
    """Raise DeleteDenied unless BOTH conditions hold. No-op for other tools."""
    if not is_gated(tool_name, tool_args):
        return

    confirmed = tool_args.get("confirm") is True
    enabled = is_enabled()
    if enabled and confirmed:
        return

    # Name EVERY missing condition, not just the first. A caller told only
    # about the confirm flag will add it, be refused again by the preference,
    # and have learned nothing about why.
    reasons = []
    if not enabled:
        reasons.append(
            f"deletion is disabled in the plugin preferences — tick "
            f"'{PREFERENCE_LABEL}' in Plugins → Claude Bridge → Configure to allow it"
        )
    raw_confirm = tool_args.get("confirm")
    if not confirmed and isinstance(raw_confirm, str):
        # A string "true" is still refused — only the JSON boolean counts —
        # but the caller DID pass something, so the stale-tool-list advice
        # below would send them round in a circle. Say what is wrong instead.
        reasons.append(
            f"confirm was the string {raw_confirm!r}; it must be the JSON boolean true "
            f"(confirm: true, not confirm: \"true\")"
        )
    elif not confirmed:
        # The stale-tool-list case is named explicitly. An MCP client caches
        # the tool list at connect time and DROPS arguments the cached schema
        # does not know about, so a client connected before this gate existed
        # strips `confirm` in flight and the caller is refused for omitting
        # something they did pass. Without this sentence the advice is
        # "do the thing you just did", which is the loop this gate's
        # every-reason-at-once rule exists to avoid. Live-hit within an hour
        # of shipping the gate, 29-Aug-2026.
        reasons.append(
            "the call did not pass confirm=true — repeat the request with "
            "confirm set to true once you are sure of the target. If you DID "
            "pass it, your MCP client is holding a tool list from before this "
            "plugin version and dropped the argument in flight: reconnect the "
            "client so it re-reads the tools, then try again"
        )
    raise DeleteDenied(
        f"'{tool_name}' refused: " + "; and ".join(reasons) +
        ". This is deliberate: an admin token alone is not enough to destroy "
        "something that cannot be recovered."
    )
