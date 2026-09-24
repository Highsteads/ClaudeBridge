#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    registry.py
# Description: The one place every built-in MCP tool is declared. Name,
#              description, schema, scope, cache behaviour, error handling and
#              the delete gate all come from a single @tool decorator, and every
#              other part of the plugin derives its view from here.
# Author:      CliveS & Claude Opus 5.5
# Date:        23-09-2026
# Version:     1.0

"""
Tool registry.

Until 3.0 a tool's metadata lived in seven places: the hand-written schema in
mcp_handler.py, a `_tool_*` wrapper, the scope sets in scope_manager.py, the
cache allow-list and invalidation map in tool_cache.py, the delete gate's set,
the handler's sensitive/redact/search-refresh sets and the README generator.
Each was kept in step by hand, and several drifted. Now a tool is one decorated
function and everything else is derived:

    @tool("list_widgets", description="...", scope="read",
          properties={...}, cacheable=True, reads={"device"})
    def list_widgets(ctx, limit=50):
        return ctx.some_handler.list_widgets(limit)

`ctx` is the MCPHandler, so a tool reaches the existing handler objects
(ctx.device_control_handler and so on) or `indigo` directly. A tool returns a
dict (or an already-serialised string); the handler turns it into the reply.

Cache buckets
-------------
`reads` names the buckets a cacheable tool's answer depends on; `invalidates`
names the buckets a mutating tool changes ({"*"} clears everything). A write
drops every cached answer whose `reads` meets its `invalidates`. The "device"
and "variable" buckets are also the real-world change domains the plugin's
deviceUpdated / variableUpdated callbacks bump. "external" is data from outside
Indigo's object model (energy files, the disk, the Mac) that no tool changes:
it is freshened by the TTL alone.

Plugin-provided tools (external_tools/) are NOT in this registry. They are
registered at runtime and keep their own dynamic-scope mechanism.
"""

from dataclasses import dataclass
from typing import Any, Callable, Dict, FrozenSet, Iterable, Optional, Tuple

SCOPES = ("read", "write", "admin")

# Every cache bucket a tool may read or invalidate. A typo in a decorator is
# caught at import rather than becoming a bucket nothing ever drops.
BUCKETS = frozenset({
    "device", "variable", "action_group", "schedule", "trigger",
    "plugin", "script", "external",
})

# Buckets freshened by the TTL alone — nothing in Claude Bridge changes them.
TTL_ONLY_BUCKETS = frozenset({"external"})

# The buckets the plugin's Indigo change callbacks track (see ToolCache): a
# device, variable or action group changed by anything, not only a tool.
CHANGE_DOMAINS = frozenset({"device", "variable", "action_group"})


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    properties: Dict[str, Any]
    required: Tuple[str, ...]
    scope: str
    func: Callable[..., Any]
    cacheable: bool = False
    reads: FrozenSet[str] = frozenset()
    invalidates: FrozenSet[str] = frozenset()
    sensitive: bool = False
    redact: bool = False
    destructive: bool = False
    refresh_search: bool = False

    @property
    def input_schema(self) -> Dict[str, Any]:
        schema: Dict[str, Any] = {"type": "object", "properties": dict(self.properties)}
        if self.required:
            schema["required"] = list(self.required)
        return schema


REGISTRY: Dict[str, ToolSpec] = {}

_ALLOWED_META = {"cacheable", "reads", "invalidates", "sensitive", "redact",
                 "destructive", "refresh_search"}


def _bucket_set(value: Optional[Iterable[str]], what: str, name: str) -> FrozenSet[str]:
    buckets = frozenset(value or ())
    unknown = buckets - BUCKETS - {"*"}
    if unknown:
        raise ValueError(f"tool {name!r}: unknown {what} bucket(s) {sorted(unknown)}")
    return buckets


def tool(name: str, *, description: str, scope: str,
         properties: Optional[Dict[str, Any]] = None,
         required: Iterable[str] = (), **meta):
    """Register the decorated function as the MCP tool `name`.

    A destructive tool gains its `confirm` argument and the gate's wording here,
    so the gate and the advertised contract cannot drift apart. `confirm` is
    declared but NOT required: a missing confirm must reach the gate and get its
    explanatory refusal, not a bare "missing required argument".
    """
    unknown_meta = set(meta) - _ALLOWED_META
    if unknown_meta:
        raise TypeError(f"tool {name!r}: unknown metadata {sorted(unknown_meta)}")
    if scope not in SCOPES:
        raise ValueError(f"tool {name!r}: scope must be one of {SCOPES}, got {scope!r}")

    props = {k: dict(v) for k, v in (properties or {}).items()}
    desc = " ".join(description.split())
    if meta.get("destructive"):
        from .security import delete_gate
        props["confirm"] = {"type": "boolean",
                            "description": delete_gate.CONFIRM_ARG_DESCRIPTION}
        desc = desc.rstrip() + delete_gate.CONFIRM_DESCRIPTION_SUFFIX

    def _register(func):
        if name in REGISTRY:
            raise ValueError(f"tool {name!r} is registered twice")
        REGISTRY[name] = ToolSpec(
            name=name,
            description=desc,
            properties=props,
            required=tuple(required),
            scope=scope,
            func=func,
            cacheable=bool(meta.get("cacheable", False)),
            reads=_bucket_set(meta.get("reads"), "reads", name),
            invalidates=_bucket_set(meta.get("invalidates"), "invalidates", name),
            sensitive=bool(meta.get("sensitive", False)),
            redact=bool(meta.get("redact", False)),
            destructive=bool(meta.get("destructive", False)),
            refresh_search=bool(meta.get("refresh_search", False)),
        )
        return func
    return _register


_loaded = False


def load() -> Dict[str, ToolSpec]:
    """Import every toolset module (which fills REGISTRY) once, and return it."""
    global _loaded
    if not _loaded:
        from . import toolsets  # noqa: F401 — importing registers the tools
        _loaded = True
    return REGISTRY


def spec_for(name: str) -> Optional[ToolSpec]:
    return load().get(name)


# ── Derived views ────────────────────────────────────────────────────────────
# Everything below is computed from REGISTRY, never kept by hand.

def names_in_scope(scope: str) -> FrozenSet[str]:
    return frozenset(n for n, s in load().items() if s.scope == scope)


def _flagged(attr: str) -> FrozenSet[str]:
    return frozenset(n for n, s in load().items() if getattr(s, attr))


def cacheable_names() -> FrozenSet[str]:
    return _flagged("cacheable")


def destructive_names() -> FrozenSet[str]:
    return _flagged("destructive")


def redact_names() -> FrozenSet[str]:
    return _flagged("redact")


def search_refresh_names() -> FrozenSet[str]:
    return _flagged("refresh_search")


def clear_all_names() -> FrozenSet[str]:
    return frozenset(n for n, s in load().items() if "*" in s.invalidates)


def reads_of(name: str) -> FrozenSet[str]:
    spec = spec_for(name)
    return spec.reads if spec else frozenset()


def invalidation_map() -> Dict[str, FrozenSet[str]]:
    """mutating tool -> the cacheable tools whose answers it drops."""
    reg = load()
    out: Dict[str, FrozenSet[str]] = {}
    for name, spec in reg.items():
        if not spec.invalidates or "*" in spec.invalidates:
            continue
        victims = frozenset(n for n, s in reg.items()
                            if s.cacheable and s.reads & spec.invalidates)
        if victims:
            out[name] = victims
    return out
