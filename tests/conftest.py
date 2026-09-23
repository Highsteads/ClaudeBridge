#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    conftest.py
# Description: Shared pytest fixtures/path-wiring for the Claude Bridge test suite.
# Author:      CliveS & Claude Opus 4.8
# Date:        06-06-2026 (shared doubles and plugin loader added 24-09-2026)
# Version:     1.1
#
# The suite imports the plugin's own modules from the REPO bundle next to this
# folder, so a local run tests the code about to be committed. Set CB_SP to a
# Server Plugin folder to test another copy, e.g. the installed one:
#   CB_SP="/Library/Application Support/Perceptive Automation/Indigo 2025.2/Plugins/Claude Bridge.indigoPlugin/Contents/Server Plugin" python3 -m pytest -q

import glob
import os
import sys
import types
from unittest.mock import MagicMock

REPO_ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir))
REPO_SERVER_PLUGIN = os.path.join(REPO_ROOT, "Claude Bridge.indigoPlugin", "Contents", "Server Plugin")


def _resolve_server_plugin() -> str:
    env = os.environ.get("CB_SP")
    if env and os.path.isdir(env):
        return env
    return REPO_SERVER_PLUGIN


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
        """Just enough of indigo.PluginBase for plugin.py to import and for its
        callbacks to be called directly. Each change callback records that the
        base class was reached, since the real one does work (it starts and
        stops the plugin's own devices and triggers)."""

        def __init__(self, *a, **k):
            pass

        def _base_called(self, name, *args):
            calls = self.__dict__.setdefault("base_calls", [])
            calls.append(name)

    for _cb in ("deviceCreated", "deviceDeleted", "deviceUpdated",
                "variableCreated", "variableDeleted", "variableUpdated",
                "actionGroupCreated", "actionGroupDeleted", "actionGroupUpdated",
                "triggerStartProcessing", "triggerStopProcessing"):
        setattr(_PluginBase, _cb,
                (lambda name: lambda self, *a: self._base_called(name, *a))(_cb))

    ind.PluginBase = _PluginBase
    ind.Dict = dict
    ind.List = list
    for attr in ("server", "devices", "variables", "kStateImageSel",
                 "activePlugin", "kDeviceAction", "Variable", "Device",
                 # Enum namespaces the handlers read at call time. The real
                 # module always has these, so a stub without them models
                 # something that cannot exist and fails tests for the wrong
                 # reason.
                 "kHvacMode", "kFanMode", "thermostat", "dimmer", "device",
                 "actionGroups", "triggers", "schedules"):
        setattr(ind, attr, MagicMock())
    sys.modules["indigo"] = ind


_install_indigo_stub()


def call_tool(ctx, tool_name, /, **args):
    """Run a registry tool the way the handler does — the same wrapper that
    serialises a dict and turns an exception into a failure payload — and
    return the parsed reply. ctx needs a `logger` plus whatever the tool
    reaches (handler objects, data_provider and so on)."""
    import json
    from mcp_server import registry
    from mcp_server.mcp_handler import MCPHandler
    spec = registry.spec_for(tool_name)
    assert spec is not None, f"no registry tool called {tool_name!r}"
    return json.loads(MCPHandler._tool_function(ctx, spec)(**args))


# ── Installed Indigo (for the live tests only) ────────────────────────────────

INDIGO_ROOT = "/Library/Application Support/Perceptive Automation"


def indigo_install_folders():
    """The versioned Indigo folders on this machine, newest first; empty on a
    machine (or CI runner) without Indigo."""
    return sorted(glob.glob(os.path.join(INDIGO_ROOT, "Indigo *")), reverse=True)


def installed_server_plugin():
    """The installed Claude Bridge Server Plugin folder, or None."""
    for d in indigo_install_folders():
        sp = os.path.join(d, "Plugins", "Claude Bridge.indigoPlugin",
                          "Contents", "Server Plugin")
        if os.path.isdir(sp):
            return sp
    return None


# ── Shared test doubles ───────────────────────────────────────────────────────

class FakeDevice:
    """A device double that carries whatever it is given. `states` defaults to
    an empty dict; `native` sets the native batteryLevel property; any other
    keyword becomes an attribute (name=, onState=, folderId= ...)."""

    def __init__(self, states=None, native=None, **attrs):
        self.states = states or {}
        if native is not None:
            self.batteryLevel = native
        for key, value in attrs.items():
            setattr(self, key, value)


# The real indigo.Dict and indigo.List are NOT dict/list subclasses, which is
# the whole reason the converters exist. So these doubles must not be either,
# or the tests would pass against code that only ever handled real dicts.

class FakeIndigoDict:
    """Stands in for indigo.Dict: has keys(), but NOT a dict subclass."""

    def __init__(self, data):
        self._d = dict(data)

    def keys(self):
        return self._d.keys()

    def __getitem__(self, k):
        return self._d[k]


class FakeIndigoList:
    """Stands in for indigo.List: iterable, but NOT a list subclass."""

    def __init__(self, items):
        self._items = list(items)

    def __iter__(self):
        return iter(self._items)


# ── plugin.py itself ──────────────────────────────────────────────────────────

_PLUGIN_MODULE = None


def load_plugin_module():
    """Import the bundle's plugin.py against the indigo stub, once.

    plugin.py reads IndigoSecrets.py and a shared plugin_utils.py from the
    Perceptive Automation folder by absolute path. Those are refused here, so a
    test never loads this Mac's real credentials and behaves the same on a CI
    runner; the bundled plugin_utils.py is still used.
    """
    global _PLUGIN_MODULE
    if _PLUGIN_MODULE is not None:
        return _PLUGIN_MODULE
    import importlib.util
    from unittest import mock

    real_spec = importlib.util.spec_from_file_location

    def _spec(name, location, *a, **k):
        if str(location).startswith(INDIGO_ROOT + "/") and "Server Plugin" not in str(location):
            return None
        return real_spec(name, location, *a, **k)

    path = os.path.join(SERVER_PLUGIN, "plugin.py")
    with mock.patch.object(importlib.util, "spec_from_file_location", _spec):
        spec = real_spec("cb_plugin_under_test", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    assert module.CLAUDEBRIDGE_BEARER_TOKEN == "", "a real IndigoSecrets.py was loaded"
    _PLUGIN_MODULE = module
    return module
