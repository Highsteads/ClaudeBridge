#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    test_v2200_high_fixes.py
# Description: Regression tests for the three high-severity findings of the
#              09-Aug-2026 deep review — the unsavable config dialog, the
#              reentrant exec lock that refused nothing, and the entity-name
#              validator that failed open into the InfluxQL builder.
# Author:      CliveS & Claude Opus 5
# Date:        09-08-2026
# Version:     1.0

import ast
import os

from conftest import SERVER_PLUGIN


# ── H1: the Configure dialog must still validate what it holds ───────────────
#
# (The Anthropic key this section once guarded went in the September 2026
# spring clean.) Asserted against the parsed source rather than by importing
# plugin.py, which needs the full Indigo host to construct.

def _validate_prefs_source() -> str:
    path = os.path.join(SERVER_PLUGIN, "plugin.py")
    with open(path, encoding="utf-8") as fh:
        tree = ast.parse(fh.read())
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "validatePrefsConfigUi":
            return ast.unparse(node)
    raise AssertionError("validatePrefsConfigUi not found in plugin.py")


def test_other_prefs_are_still_validated():
    """Removing the key check must not have gutted the rest of the validator."""
    src = _validate_prefs_source()
    assert "errors_dict['log_level']" in src


# ── H2 (the reentrant exec lock that refused nothing) is superseded by the 3.0
# job mechanism; its behaviours are covered in test_exec_lock.py.
