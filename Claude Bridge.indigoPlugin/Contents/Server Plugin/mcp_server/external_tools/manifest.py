#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    manifest.py
# Description: Parsing and validation of a plugin-provided MCP tool manifest
#              (provider-manifest v1). This is the contract mlamoure's Indigo
#              MCP Server published in docs/mcp-provider-manifest.md
#              (v2026.8.1): any Indigo plugin may ship
#              Contents/Resources/mcp-manifest.json, and a server that reads it
#              lists the tools to the AI as {prefix}_{name} and forwards calls
#              to the plugin's hidden invoke action. Claude Bridge implements
#              the same contract from that published specification so a
#              provider written for either server works with both; this file
#              is the single authority here on what a valid manifest is.
#              Pure stdlib, no indigo import, so it is directly unit-testable.
# Author:      CliveS & Claude Fable 5.1
# Date:        10-09-2026
# Version:     1.0

import json
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List

MANIFEST_VERSION          = 1
MANIFEST_FILENAME         = "mcp-manifest.json"
DEFAULT_INVOKE_ACTION_ID  = "mcp_tool_invoke"

TOOL_NAME_RE = re.compile(r"^[a-z][a-z0-9_]{0,40}$")
PREFIX_RE    = re.compile(r"^[a-z][a-z0-9_]{0,31}$")

DEFAULT_TIMEOUT_SECONDS = 30
MIN_TIMEOUT_SECONDS     = 5
MAX_TIMEOUT_SECONDS     = 120


class ManifestError(Exception):
    """The manifest is malformed or breaks the provider contract."""


@dataclass
class ExternalTool:
    name: str
    description: str
    input_schema: Dict[str, Any]
    write: bool
    timeout_seconds: int
    action_id: str


@dataclass
class ProviderManifest:
    plugin_id: str
    display_name: str
    prefix: str
    tools: List[ExternalTool] = field(default_factory=list)
    path: str = ""

    def exposed_name(self, tool: ExternalTool) -> str:
        return f"{self.prefix}_{tool.name}"


def derive_prefix(plugin_id: str) -> str:
    """The default tool prefix: the plugin id's last dot-segment, snake-cased.
    com.vtmikel.autolights -> autolights; com.foo.example-http-responder ->
    example_http_responder. Must start with a letter, so leading digits and
    punctuation go; an id that leaves nothing usable becomes "plugin"."""
    segment = str(plugin_id or "").rsplit(".", 1)[-1].lower()
    segment = re.sub(r"[^a-z0-9_]", "_", segment)
    segment = re.sub(r"^[^a-z]+", "", segment)
    segment = re.sub(r"_+", "_", segment).strip("_") or "plugin"
    return segment[:32]


def parse_manifest(text: str, expected_plugin_id: str, path: str = "") -> ProviderManifest:
    """Parse and validate one manifest file's contents.

    `expected_plugin_id` is the CFBundleIdentifier of the bundle the file was
    found in; the manifest's own provider.plugin_id must match it, so a
    bundle cannot claim to speak for another plugin. Raises ManifestError on
    any violation — one reason, naming the offending field.
    """
    try:
        data = json.loads(text)
    except (json.JSONDecodeError, TypeError) as exc:
        raise ManifestError(f"not valid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise ManifestError("manifest root must be a JSON object")

    version = data.get("manifest_version")
    if version != MANIFEST_VERSION:
        raise ManifestError(
            f"unsupported manifest_version {version!r} (this server reads v{MANIFEST_VERSION})")

    provider = data.get("provider")
    if not isinstance(provider, dict) or not provider.get("plugin_id"):
        raise ManifestError("provider.plugin_id is required")
    plugin_id = str(provider["plugin_id"])
    if plugin_id != expected_plugin_id:
        raise ManifestError(
            f"provider.plugin_id {plugin_id!r} does not match the bundle it was found in "
            f"({expected_plugin_id!r})")
    display_name = str(provider.get("display_name") or plugin_id)

    declared_prefix = data.get("tool_prefix")
    if declared_prefix is not None:
        # A declared prefix is checked, never quietly replaced: silently
        # substituting one would surprise the author who wrote it.
        if not isinstance(declared_prefix, str) or not PREFIX_RE.match(declared_prefix):
            raise ManifestError(
                f"tool_prefix {declared_prefix!r} is invalid (must match {PREFIX_RE.pattern})")
        prefix = declared_prefix
    else:
        prefix = derive_prefix(plugin_id)

    default_action_id = data.get("invoke_action_id", DEFAULT_INVOKE_ACTION_ID)
    if not isinstance(default_action_id, str) or not default_action_id.strip():
        raise ManifestError("invoke_action_id must be a non-empty string")

    raw_tools = data.get("tools")
    if not isinstance(raw_tools, list) or not raw_tools:
        raise ManifestError("tools must be a non-empty array")

    tools: List[ExternalTool] = []
    seen = set()
    for i, raw in enumerate(raw_tools):
        if not isinstance(raw, dict):
            raise ManifestError(f"tools[{i}] must be an object")
        name = raw.get("name")
        if not isinstance(name, str) or not TOOL_NAME_RE.match(name):
            raise ManifestError(
                f"tools[{i}].name {name!r} is invalid (must match {TOOL_NAME_RE.pattern})")
        if name in seen:
            raise ManifestError(f"duplicate tool name {name!r}")
        seen.add(name)

        description = raw.get("description")
        if not isinstance(description, str) or not description.strip():
            raise ManifestError(f"tools[{i}].description is required")

        schema = raw.get("inputSchema")
        if not isinstance(schema, dict) or schema.get("type") != "object":
            raise ManifestError(
                f"tools[{i}].inputSchema must be a JSON Schema object with type 'object'")

        # An undeclared write flag is treated as a write, so the write gate
        # fails safe for a provider that forgot to say.
        write = raw.get("write", True)
        if not isinstance(write, bool):
            raise ManifestError(f"tools[{i}].write must be true or false")

        timeout = raw.get("timeout_seconds", DEFAULT_TIMEOUT_SECONDS)
        if isinstance(timeout, bool) or not isinstance(timeout, int):
            raise ManifestError(f"tools[{i}].timeout_seconds must be an integer")
        timeout = max(MIN_TIMEOUT_SECONDS, min(MAX_TIMEOUT_SECONDS, timeout))

        action_id = raw.get("action_id", default_action_id)
        if not isinstance(action_id, str) or not action_id.strip():
            raise ManifestError(f"tools[{i}].action_id must be a non-empty string")

        tools.append(ExternalTool(
            name=name,
            description=description.strip(),
            input_schema=schema,
            write=write,
            timeout_seconds=timeout,
            action_id=action_id,
        ))

    return ProviderManifest(plugin_id=plugin_id, display_name=display_name,
                            prefix=prefix, tools=tools, path=path)
