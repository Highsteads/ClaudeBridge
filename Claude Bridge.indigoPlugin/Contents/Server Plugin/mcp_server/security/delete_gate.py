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

from typing import Any, Dict, Set

from .. import runtime_config

# Deletes with no recovery path inside Indigo or ClaudeBridge. Deliberately NOT
# every tool whose name starts with "delete_" — see the module docstring.
DESTRUCTIVE_TOOLS: Set[str] = {
    "delete_trigger",
    "delete_schedule",
    "delete_action_group",
    "delete_device",
    "variable_delete",
    # Folder deletes can cascade into their contents, so they are strictly
    # worse than deleting one object.
    "delete_device_folder",
    "delete_variable_folder",
}

# The pluginPrefs key and the label a user sees, kept together so an error
# message can tell someone exactly which checkbox to tick.
PREFERENCE_KEY   = "allow_destructive_delete"
PREFERENCE_LABEL = "Allow Claude to delete devices, variables and automations"


# The wording appended to every gated tool's description, and the description
# of the argument itself. Named constants because TWO things publish them: the
# handler at registration, and scripts/generate_tool_doc.py when it writes the
# README table. Hard-coding the text in both is how a documented contract comes
# to disagree with the live one.
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
    trap that made `is_influx_enabled` read backwards in v2.20.2.
    """
    return runtime_config.get_bool(PREFERENCE_KEY, False)


def check(tool_name: str, tool_args: Dict[str, Any]) -> None:
    """Raise DeleteDenied unless BOTH conditions hold. No-op for other tools."""
    if tool_name not in DESTRUCTIVE_TOOLS:
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
    if not confirmed:
        reasons.append(
            "the call did not pass confirm=true — repeat the request with "
            "confirm set to true once you are sure of the target"
        )
    raise DeleteDenied(
        f"'{tool_name}' refused: " + "; and ".join(reasons) +
        ". This is deliberate: an admin token alone is not enough to destroy "
        "something that cannot be recovered."
    )
