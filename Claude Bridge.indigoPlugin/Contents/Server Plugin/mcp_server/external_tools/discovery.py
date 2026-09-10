#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    discovery.py
# Description: Finds provider manifests on disk. Walks every installed plugin
#              bundle Indigo knows about — enabled or disabled — and reads
#              Contents/Resources/mcp-manifest.json where one exists.
#              Filesystem only, no cross-plugin calls: cheap, silent for the
#              plugins that do not take part, and it sees a provider that is
#              currently disabled (its tools then fail at call time with a
#              clear "not running", which beats a silent absence). Also
#              produces a cheap fingerprint of the manifest files so the
#              handler can notice a new or changed one without re-parsing.
# Author:      CliveS & Claude Fable 5.1
# Date:        10-09-2026
# Version:     1.0

import logging
import os
from typing import Iterable, List, Optional, Tuple

from .manifest import MANIFEST_FILENAME, ManifestError, ProviderManifest, parse_manifest

try:
    import indigo
except ImportError:      # unit tests run outside the plugin host
    indigo = None


def manifest_path_for(plugin_folder_path: str) -> str:
    return os.path.join(plugin_folder_path, "Contents", "Resources", MANIFEST_FILENAME)


def _installed_plugins(plugin_list=None) -> list:
    """(plugin_id, folder) for every installed bundle. `plugin_list` is
    injectable for tests; the default asks Indigo, disabled plugins included."""
    if plugin_list is None:
        if indigo is None:
            return []
        try:
            plugin_list = indigo.server.getPluginList(includeDisabled=True)
        except Exception:
            return []
    out = []
    for p in plugin_list:
        try:
            pid, folder = p.pluginId, p.pluginFolderPath
        except Exception:
            continue
        if pid and folder:
            out.append((str(pid), str(folder)))
    return out


def discover_manifests(logger: Optional[logging.Logger] = None,
                       self_plugin_id: str = "",
                       plugin_list=None) -> List[ProviderManifest]:
    """Parsed manifests for every installed plugin that ships a valid one.
    An invalid manifest is skipped with ONE warning naming the file and the
    reason; our own bundle is never a provider to itself."""
    logger = logger or logging.getLogger("Plugin")
    found: List[ProviderManifest] = []
    for pid, folder in _installed_plugins(plugin_list):
        if pid == self_plugin_id:
            continue
        path = manifest_path_for(folder)
        if not os.path.isfile(path):
            continue
        try:
            with open(path, "r", encoding="utf-8") as f:
                text = f.read()
            found.append(parse_manifest(text, expected_plugin_id=pid, path=path))
        except (ManifestError, OSError, UnicodeDecodeError) as exc:
            logger.warning(f"⚠️ Ignoring MCP tool manifest {path}: {exc}")
    return found


def manifest_fingerprint(self_plugin_id: str = "", plugin_list=None) -> Tuple[Tuple[str, int, int], ...]:
    """(path, mtime_ns, size) of every manifest file present, sorted. A
    changed tuple means a manifest appeared, vanished or was rewritten —
    the trigger for a rescan, at the cost of one stat() per bundle."""
    rows = []
    for pid, folder in _installed_plugins(plugin_list):
        if pid == self_plugin_id:
            continue
        path = manifest_path_for(folder)
        try:
            st = os.stat(path)
        except OSError:
            continue
        rows.append((path, int(st.st_mtime_ns), int(st.st_size)))
    return tuple(sorted(rows))


def provider_ids(manifests: Iterable[ProviderManifest]) -> List[str]:
    return [m.plugin_id for m in manifests]
