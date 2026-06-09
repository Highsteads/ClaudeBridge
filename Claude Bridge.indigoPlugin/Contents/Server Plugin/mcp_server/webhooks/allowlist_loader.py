"""
Builds the egress Allowlist from its sources, re-read fresh on every call.

Sources are UNIONed (any one can grant a host):
  1. static_entries / static_http_entries — captured by the plugin at startup /
     config-save from IndigoSecrets.WEBHOOK_ALLOWLIST and the PluginConfig field.
  2. webhook_allowlist.json (optional) in the plugin's Preferences folder — read
     LIVE here, so an operator can add a destination without a plugin restart.
     Shape: {"allow_hosts": [...], "allow_http_hosts": [...], "allow_extra_cidrs": [...]}.

Fail-closed: a missing/corrupt JSON file is ignored (we fall back to the static
entries — narrower, never wider). An entirely empty result means deny-all, which
the handler reports clearly at registration time.

Original ClaudeBridge implementation, stdlib only.
"""

import json
import logging
import os
from typing import List, Optional, Sequence

from ..security.egress_guard import Allowlist

_logger = logging.getLogger("Plugin")


def load_allowlist(
    static_entries: Optional[Sequence[str]] = None,
    static_http_entries: Optional[Sequence[str]] = None,
    json_path: Optional[str] = None,
) -> Allowlist:
    """Return a freshly-built Allowlist unioning the static entries with the
    on-disk JSON file (if present)."""
    entries: List[str] = list(static_entries or [])
    http_entries: List[str] = list(static_http_entries or [])

    if json_path and os.path.exists(json_path):
        try:
            with open(json_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            entries += list(data.get("allow_hosts", []) or [])
            entries += list(data.get("allow_extra_cidrs", []) or [])
            http_entries += list(data.get("allow_http_hosts", []) or [])
        except Exception as e:
            # Fail-closed: ignore a bad file, keep only the static entries.
            _logger.error(f"webhook_allowlist.json unreadable ({e}); ignoring it")

    return Allowlist.from_entries(entries, http_entries)
