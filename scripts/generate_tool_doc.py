#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    generate_tool_doc.py
# Description: Generate the MCP tool reference (docs/tools.md) from the live
#              tool registry. Single source of truth is mcp_handler.py (tool name
#              + description) cross-referenced with scope_manager.py
#              (read/write/admin tier). No Indigo import — pure static AST parse,
#              runs anywhere.
# Author:      CliveS & Claude Opus 4.8; Claude Fable 5.1 (1.1)
# Date:        08-06-2026 (1.1: 11-09-2026)
# Version:     1.1
#
# v1.1 (11-09-2026): the table moved out of the README into docs/tools.md, a page
#   of the documentation site (GitHub Pages). The README is a front page now and
#   carries the tier counts only. Same markers, same --write / --check contract.
#   Also: a blank line before the END marker, or kramdown drops the last table.
#
# Usage:
#   python3 scripts/generate_tool_doc.py            # print the table to stdout
#   python3 scripts/generate_tool_doc.py --write    # inject into docs/tools.md between markers
#   python3 scripts/generate_tool_doc.py --check     # exit 1 if docs/tools.md is stale or a tool is unclassified
#
# The table is written between these markers in docs/tools.md:
#   <!-- BEGIN TOOL TABLE -->
#   <!-- END TOOL TABLE -->

import argparse
import ast
import os
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BUNDLE_SP = os.path.join(
    REPO_ROOT, "Claude Bridge.indigoPlugin", "Contents", "Server Plugin"
)
HANDLER_PATH = os.path.join(BUNDLE_SP, "mcp_server", "mcp_handler.py")
SCOPE_PATH = os.path.join(BUNDLE_SP, "mcp_server", "security", "scope_manager.py")
GATE_PATH = os.path.join(BUNDLE_SP, "mcp_server", "security", "delete_gate.py")
DOC_PATH = os.path.join(REPO_ROOT, "docs", "tools.md")
README_PATH = DOC_PATH   # kept for anything that imported the old name

BEGIN_MARKER = "<!-- BEGIN TOOL TABLE -->"
END_MARKER = "<!-- END TOOL TABLE -->"

# Display order + heading for each scope tier.
SCOPE_ORDER = [
    ("read", "Read tools", "Pure queries — no state change. Require the `read` scope."),
    ("write", "Write tools", "Modify Indigo state. Require `write` (or `admin`)."),
    (
        "admin",
        "Admin tools",
        "Destructive / irreversible / code-execution / lifecycle / physical-security. Require `admin`.",
    ),
]


def _read(path):
    # Indigo's embedded Python defaults open() to ASCII; be explicit (UTF-8 source).
    with open(path, encoding="utf-8") as f:
        return f.read()


def parse_tools(handler_src):
    """Return {tool_name: description} for every self._tools["x"] = {...} literal."""
    tools = {}
    tree = ast.parse(handler_src)
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        for target in node.targets:
            # Match  self._tools["name"]
            if (
                isinstance(target, ast.Subscript)
                and isinstance(target.value, ast.Attribute)
                and target.value.attr == "_tools"
                and isinstance(target.slice, ast.Constant)
                and isinstance(target.slice.value, str)
            ):
                name = target.slice.value
                desc = ""
                if isinstance(node.value, ast.Dict):
                    for k, v in zip(node.value.keys, node.value.values):
                        if (
                            isinstance(k, ast.Constant)
                            and k.value == "description"
                            and isinstance(v, ast.Constant)
                            and isinstance(v.value, str)
                        ):
                            desc = v.value.strip()
                            break
                tools[name] = desc
    return tools


def parse_delete_gate(gate_src):
    """Return (destructive_tool_names, description_suffix) from delete_gate.py.

    The gated tools have their description extended at REGISTRATION time, not
    in the `self._tools[...] = {...}` literal, so a static parse of the handler
    alone silently understates what those tools require — which is the exact
    kind of doc/runtime drift this generator exists to prevent. Parsed rather
    than imported to keep the "runs anywhere, no Indigo" property.
    """
    names, suffix = set(), ""
    tree = ast.parse(gate_src)
    for node in ast.walk(tree):
        targets, value = [], None
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            targets, value = [node.target.id], node.value
        elif isinstance(node, ast.Assign):
            targets = [t.id for t in node.targets if isinstance(t, ast.Name)]
            value = node.value
        for tname in targets:
            if tname == "DESTRUCTIVE_TOOLS" and isinstance(value, ast.Set):
                names = {e.value for e in value.elts
                         if isinstance(e, ast.Constant) and isinstance(e.value, str)}
            elif tname == "CONFIRM_DESCRIPTION_SUFFIX":
                try:
                    suffix = ast.literal_eval(value)
                except (ValueError, SyntaxError):
                    suffix = ""
    return names, suffix


def parse_scope_sets(scope_src):
    """Return {tool_name: 'read'|'write'|'admin'} from the three classification sets."""
    set_to_scope = {
        "READ_TOOLS": "read",
        "WRITE_TOOLS": "write",
        "ADMIN_TOOLS": "admin",
    }
    scopes = {}
    tree = ast.parse(scope_src)
    for node in ast.walk(tree):
        # Sets are declared as either `READ_TOOLS: Set[str] = {...}` (AnnAssign)
        # or `READ_TOOLS = {...}` (Assign). Handle both.
        targets = []
        value = None
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            targets = [node.target.id]
            value = node.value
        elif isinstance(node, ast.Assign):
            targets = [t.id for t in node.targets if isinstance(t, ast.Name)]
            value = node.value
        for tname in targets:
            scope = set_to_scope.get(tname)
            if scope and isinstance(value, ast.Set):
                for elt in value.elts:
                    if isinstance(elt, ast.Constant) and isinstance(elt.value, str):
                        scopes[elt.value] = scope
    return scopes


def build_table(tools, scopes):
    """Return (markdown, warnings). Mirrors required_scope_for: unlisted == admin."""
    warnings = []
    # Bucket tools by their effective scope.
    buckets = {"read": [], "write": [], "admin": []}
    for name in sorted(tools):
        scope = scopes.get(name)
        if scope is None:
            # Fail-closed default — same as required_scope_for() at runtime.
            scope = "admin"
            warnings.append(
                f"{name!r} is not in READ/WRITE/ADMIN_TOOLS — defaulting to admin "
                f"(runtime audit_classification() will ERROR on this)."
            )
        buckets[scope].append(name)

    total = len(tools)
    lines = [
        f"<!-- AUTO-GENERATED by scripts/generate_tool_doc.py — {total} tools. Do not edit by hand. -->",
        "",
    ]
    for scope, heading, blurb in SCOPE_ORDER:
        names = buckets[scope]
        if not names:
            continue
        lines.append(f"### {heading} ({len(names)})")
        lines.append("")
        lines.append(f"_{blurb}_")
        lines.append("")
        lines.append("| Tool | Description |")
        lines.append("|------|-------------|")
        for name in names:
            desc = tools[name].replace("\n", " ").replace("|", "\\|").strip()
            lines.append(f"| `{name}` | {desc} |")
        lines.append("")
    # The trailing BLANK line matters: the END marker follows the table, and
    # kramdown (GitHub Pages) refuses to parse a table whose block also holds a
    # line with no pipe in it — the whole admin table rendered as a paragraph
    # until this was measured (11-09-2026). GitHub's README renderer forgave it.
    return "\n".join(lines).rstrip() + "\n\n", warnings


def inject(readme_src, table_md):
    """Replace content between the markers. Returns the new page text."""
    if BEGIN_MARKER not in readme_src or END_MARKER not in readme_src:
        raise SystemExit(
            f"docs/tools.md is missing the markers.\nAdd these two lines where the "
            f"table should go:\n  {BEGIN_MARKER}\n  {END_MARKER}"
        )
    pre = readme_src.split(BEGIN_MARKER)[0]
    post = readme_src.split(END_MARKER)[1]
    return f"{pre}{BEGIN_MARKER}\n{table_md}{END_MARKER}{post}"


def main():
    ap = argparse.ArgumentParser(description="Generate the MCP tool reference, docs/tools.md.")
    ap.add_argument("--write", action="store_true", help="inject into docs/tools.md")
    ap.add_argument(
        "--check",
        action="store_true",
        help="exit 1 if docs/tools.md is stale or any tool is unclassified",
    )
    args = ap.parse_args()

    tools = parse_tools(_read(HANDLER_PATH))
    scopes = parse_scope_sets(_read(SCOPE_PATH))

    # Mirror the registration-time augmentation so the table states the real
    # contract for a gated delete rather than the bare literal.
    gated, suffix = parse_delete_gate(_read(GATE_PATH))
    for name in gated:
        if name in tools and suffix and suffix.strip() not in tools[name]:
            tools[name] = tools[name].rstrip() + suffix
    table_md, warnings = build_table(tools, scopes)

    for w in warnings:
        print(f"WARNING: {w}", file=sys.stderr)

    if args.check:
        current = _read(DOC_PATH)
        expected = inject(current, table_md)
        stale = current != expected
        if warnings:
            print("FAIL: one or more tools are unclassified.", file=sys.stderr)
        if stale:
            print(
                "FAIL: docs/tools.md tool table is stale — run "
                "`python3 scripts/generate_tool_doc.py --write`.",
                file=sys.stderr,
            )
        sys.exit(1 if (stale or warnings) else 0)

    if args.write:
        new = inject(_read(DOC_PATH), table_md)
        with open(DOC_PATH, "w", encoding="utf-8") as f:
            f.write(new)
        print(f"Wrote {len(tools)} tools into {DOC_PATH}")
    else:
        print(table_md)


if __name__ == "__main__":
    main()
