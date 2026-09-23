#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    test_no_third_party_deps.py
# Description: The plugin needs nothing beyond the standard library and Indigo
#              itself. Until the September 2026 spring clean it pulled anthropic,
#              pydantic, influxdb and jinja2 onto every user's machine for one
#              optional tool. This pins the new state: no requirements.txt in the
#              bundle, and no module in it imports a package the embedded Python
#              does not already carry.
# Author:      CliveS & Claude Opus 5.5
# Date:        23-09-2026
# Version:     1.0

import ast
import os
import sys

from conftest import SERVER_PLUGIN

# Names that resolve without pip: Indigo's own module, the plugin's own
# packages and modules, and the shared files plugin.py loads by path.
_ALLOWED = {
    "indigo",
    "mcp_server", "plugin_utils", "indigo_mcp_proxy",
    "IndigoSecrets", "conftest",
}

# The packages the old requirements.txt installed, plus the two transitive ones
# the removed code reached for directly. Named so a failure says which came back.
_RETIRED = {"anthropic", "pydantic", "influxdb", "jinja2", "pytz", "httpx"}


def _bundle_sources():
    for root, dirs, files in os.walk(SERVER_PLUGIN):
        dirs[:] = [d for d in dirs if d not in ("__pycache__", "Packages")]
        for name in files:
            if name.endswith(".py"):
                yield os.path.join(root, name)


def _top_level_imports(path):
    with open(path, encoding="utf-8") as fh:
        tree = ast.parse(fh.read(), filename=path)
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                yield alias.name.split(".")[0], node.lineno
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            yield node.module.split(".")[0], node.lineno


def test_bundle_ships_no_requirements_file():
    path = os.path.join(SERVER_PLUGIN, "requirements.txt")
    assert not os.path.exists(path), (
        "requirements.txt is back in the bundle — Indigo will pip-install it on "
        "every user's machine. The plugin is meant to need no extra packages."
    )


def test_every_import_is_stdlib_indigo_or_our_own():
    stdlib = set(sys.stdlib_module_names)
    offenders = []
    for path in _bundle_sources():
        for name, line in _top_level_imports(path):
            if name in stdlib or name in _ALLOWED:
                continue
            rel = os.path.relpath(path, SERVER_PLUGIN)
            offenders.append(f"{rel}:{line} imports {name}")
    assert not offenders, "third-party imports in the bundle:\n" + "\n".join(offenders)


def test_retired_packages_are_not_imported_anywhere():
    hits = []
    for path in _bundle_sources():
        for name, line in _top_level_imports(path):
            if name in _RETIRED:
                hits.append(f"{os.path.relpath(path, SERVER_PLUGIN)}:{line} {name}")
    assert not hits, "\n".join(hits)


def test_the_scan_can_fail():
    """A guard that cannot fail proves nothing: feed it a known offender."""
    import tempfile
    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False,
                                     encoding="utf-8") as fh:
        fh.write("import anthropic\nfrom pydantic import BaseModel\nimport json\n")
        tmp = fh.name
    try:
        names = {n for n, _ in _top_level_imports(tmp)}
    finally:
        os.unlink(tmp)
    assert {"anthropic", "pydantic"} <= names
    assert not ({"anthropic", "pydantic"} & set(sys.stdlib_module_names))
