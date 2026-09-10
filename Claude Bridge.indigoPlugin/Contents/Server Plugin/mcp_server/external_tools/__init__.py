#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    __init__.py
# Description: Plugin-provided MCP tools (provider-manifest v1). See
#              manifest.py for the contract, discovery.py for how manifests are
#              found, dispatch.py for the cross-plugin call, manager.py for the
#              registry entries the handler serves.
# Author:      CliveS & Claude Fable 5.1
# Date:        10-09-2026
# Version:     1.0

from .discovery import discover_manifests, manifest_fingerprint, manifest_path_for, provider_ids
from .dispatch import invoke_provider_tool, parse_envelope
from .manager import WRITE_GATE_MESSAGE, ExternalToolManager
from .manifest import (
    DEFAULT_INVOKE_ACTION_ID,
    MANIFEST_FILENAME,
    MANIFEST_VERSION,
    ExternalTool,
    ManifestError,
    ProviderManifest,
    derive_prefix,
    parse_manifest,
)

__all__ = [
    "DEFAULT_INVOKE_ACTION_ID", "MANIFEST_FILENAME", "MANIFEST_VERSION", "WRITE_GATE_MESSAGE",
    "ExternalTool", "ExternalToolManager", "ManifestError", "ProviderManifest",
    "derive_prefix", "discover_manifests", "invoke_provider_tool", "manifest_fingerprint",
    "manifest_path_for", "parse_envelope", "parse_manifest", "provider_ids",
]
