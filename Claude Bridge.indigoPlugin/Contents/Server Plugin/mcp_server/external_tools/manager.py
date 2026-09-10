#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    manager.py
# Description: Turns discovered provider manifests into tool-registry entries
#              shaped exactly like Claude Bridge's own ({description,
#              inputSchema, function}), so the handler's tools/list and
#              tools/call need no special case. The exposed name is ALWAYS
#              "{prefix}_{name}" — a bare provider name never reaches a
#              client — and prefixes are claimed first-come across providers,
#              so two plugins can never fight over a namespace. A name that
#              would shadow a built-in tool is skipped, loudly. Every write
#              tool checks the write gate at call time, so the Configure
#              checkbox applies without a restart.
# Author:      CliveS & Claude Fable 5.1
# Date:        10-09-2026
# Version:     1.0

import logging
from typing import Callable, Dict, Iterable, List, Optional

from ..common.json_encoder import safe_json_dumps
from .discovery import discover_manifests
from .dispatch import invoke_provider_tool
from .manifest import ExternalTool, ProviderManifest

WRITE_GATE_MESSAGE = (
    "Plugin-provided write tools are switched off — tick 'Allow plugin-provided "
    "tools to make changes' under Plugins > Claude Bridge > Configure to enable them.")


class ExternalToolManager:
    def __init__(
        self,
        logger: Optional[logging.Logger] = None,
        self_plugin_id: str = "",
        write_gate_supplier: Optional[Callable[[], bool]] = None,
        get_plugin: Optional[Callable[[str], object]] = None,
    ):
        self.logger = logger or logging.getLogger("Plugin")
        self.self_plugin_id = self_plugin_id
        # Consulted on every write call, never cached, so a Configure save
        # takes effect immediately.
        self.write_gate_supplier = write_gate_supplier or (lambda: True)
        self._get_plugin = get_plugin
        self.manifests: List[ProviderManifest] = []
        self.rejected: List[str] = []        # manifests refused this scan, for the menu print
        self.skipped_names: List[str] = []   # exposed names dropped for colliding with a built-in

    # ── scanning ─────────────────────────────────────────────────────────

    def rescan(self, builtin_names: Iterable[str], plugin_list=None) -> Dict[str, dict]:
        """Re-discover manifests and build registry entries for every tool.
        Returns {exposed_name: entry}. The manager keeps the accepted
        manifests for provider_ids() and summary()."""
        builtin = set(builtin_names or ())
        manifests = discover_manifests(self.logger, self_plugin_id=self.self_plugin_id,
                                       plugin_list=plugin_list)
        accepted: List[ProviderManifest] = []
        owner: Dict[str, str] = {}
        self.rejected = []
        for m in manifests:
            holder = owner.get(m.prefix)
            if holder is not None and holder != m.plugin_id:
                self.logger.error(
                    f"❌ MCP tool prefix '{m.prefix}' is already claimed by {holder}; "
                    f"rejecting the manifest from {m.plugin_id}")
                self.rejected.append(m.plugin_id)
                continue
            owner[m.prefix] = m.plugin_id
            accepted.append(m)
        self.manifests = accepted

        entries: Dict[str, dict] = {}
        self.skipped_names = []
        for m in accepted:
            for tool in m.tools:
                exposed = m.exposed_name(tool)
                if exposed in builtin:
                    self.logger.warning(
                        f"⚠️ Plugin-provided tool '{exposed}' from {m.plugin_id} would shadow "
                        f"a built-in tool — skipped")
                    self.skipped_names.append(exposed)
                    continue
                entries[exposed] = {
                    "description":       f"{tool.description} [provided by the {m.display_name} plugin]",
                    "inputSchema":       tool.input_schema,
                    "function":          self._make_function(m, tool),
                    "external_provider": m.plugin_id,
                    "write":             tool.write,
                }
        return entries

    def provider_ids(self) -> List[str]:
        return [m.plugin_id for m in self.manifests]

    def summary(self) -> List[str]:
        """Human-readable lines for the Print menu item / log."""
        lines = []
        for m in self.manifests:
            lines.append(f"{m.display_name} ({m.plugin_id}) — prefix '{m.prefix}', "
                         f"{len(m.tools)} tool(s), manifest {m.path}")
            for t in m.tools:
                lines.append(f"    {m.exposed_name(t)}  [{'write' if t.write else 'read'}, "
                             f"{t.timeout_seconds}s]")
        for pid in self.rejected:
            lines.append(f"REJECTED {pid} — its prefix is already claimed (see the event log)")
        for name in self.skipped_names:
            lines.append(f"SKIPPED {name} — collides with a built-in tool")
        return lines

    # ── call wrappers ────────────────────────────────────────────────────

    def _make_function(self, manifest: ProviderManifest, tool: ExternalTool) -> Callable[..., str]:
        def fn(**kwargs) -> str:
            # **kwargs, so an unknown argument cannot TypeError here: the
            # provider's own validation is the authority and its refusal
            # comes back in-band for the model to correct on. The handler's
            # schema check already refused arguments the manifest does not
            # declare.
            if tool.write and not self.write_gate_supplier():
                return safe_json_dumps({"success": False, "provider": manifest.plugin_id,
                                        "error": WRITE_GATE_MESSAGE})
            return safe_json_dumps(invoke_provider_tool(
                provider_id=manifest.plugin_id,
                action_id=tool.action_id,
                bare_name=tool.name,
                display_name=manifest.display_name,
                arguments=kwargs,
                timeout_seconds=tool.timeout_seconds,
                logger=self.logger,
                get_plugin=self._get_plugin,
            ))
        fn.__name__ = manifest.exposed_name(tool)
        return fn
