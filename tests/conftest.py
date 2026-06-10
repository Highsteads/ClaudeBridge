#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    conftest.py
# Description: Shared pytest fixtures/path-wiring for the Claude Bridge test suite.
# Author:      CliveS & Claude Opus 4.8
# Date:        06-06-2026
# Version:     1.0
#
# The suite imports the plugin's own modules. We resolve the live installed
# bundle (the code that actually runs) so the tests verify what is deployed,
# falling back to the repo bundle. Override with the CB_SP env var if needed.

import glob
import os
import sys
import types
from unittest.mock import MagicMock


def _resolve_server_plugin() -> str:
    env = os.environ.get("CB_SP")
    if env and os.path.isdir(env):
        return env
    base = "/Library/Application Support/Perceptive Automation"
    for d in sorted(glob.glob(os.path.join(base, "Indigo *")), reverse=True):
        sp = os.path.join(d, "Plugins", "Claude Bridge.indigoPlugin",
                          "Contents", "Server Plugin")
        if os.path.isdir(sp):
            return sp
    # Repo-bundle fallback, derived from this file's location so the suite
    # runs on any checkout path (CI runners, other machines).
    return os.path.normpath(os.path.join(
        os.path.dirname(os.path.abspath(__file__)), os.pardir,
        "Claude Bridge.indigoPlugin", "Contents", "Server Plugin",
    ))


SERVER_PLUGIN = _resolve_server_plugin()
PACKAGES      = os.path.join(os.path.dirname(SERVER_PLUGIN), "Packages")

for _p in (PACKAGES, SERVER_PLUGIN):
    if os.path.isdir(_p) and _p not in sys.path:
        sys.path.insert(0, _p)


def _install_indigo_stub() -> None:
    """Stub the `indigo` module so plugin modules that `import indigo` load
    standalone under plain pytest (outside IndigoPluginHost3)."""
    if "indigo" in sys.modules:
        return
    ind = types.ModuleType("indigo")

    class _PluginBase:
        def __init__(self, *a, **k):
            pass

    ind.PluginBase = _PluginBase
    ind.Dict = dict
    ind.List = list
    for attr in ("server", "devices", "variables", "kStateImageSel",
                 "activePlugin", "kDeviceAction", "Variable", "Device"):
        setattr(ind, attr, MagicMock())
    sys.modules["indigo"] = ind


_install_indigo_stub()
