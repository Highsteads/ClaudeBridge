#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    test_coercion.py
# Description: Argument coercion: string booleans, bools refused as entity IDs,
#              and Indigo's string conventions for variable values.
# Author:      CliveS & Claude Opus 5.5
# Date:        24-09-2026
# Version:     1.0
#
# Moved unchanged from the release-named files in the 3.0 spring clean:
#   test_v2101_fixes.py, test_v2201_medium_fixes.py, test_v284_fixes.py
# except test_handlers_refuse_a_bool_as_an_id, which replaced an AST check on the
# handlers' source text and now calls the handlers.


import logging

import pytest

from mcp_server.tools.device_control.device_control_handler import DeviceControlHandler


# ── _coerce_bool: string "false" must be False (bool('false') is True) ───────

def test_coerce_bool_string_false_is_false():
    from mcp_server.tools.extended_tools.extended_tools_handler import _coerce_bool
    assert _coerce_bool("false") is False
    assert _coerce_bool("0") is False
    assert _coerce_bool("") is False
    assert _coerce_bool("no") is False
    assert _coerce_bool("true") is True
    assert _coerce_bool("1") is True
    assert _coerce_bool(True) is True
    assert _coerce_bool(False) is False


# ── Bools must never be accepted as entity IDs ───────────────────────────────
# bool subclasses int, so an isinstance(x, int) check waves True/False through
# as IDs 1 and 0. folder_id 0 is a REAL destination (root), which is what makes
# a stray `false` dangerous rather than merely wrong.

def test_extended_tools_coerce_id_rejects_bools():
    from mcp_server.tools.extended_tools.extended_tools_handler import _coerce_id

    assert _coerce_id(42) == 42
    assert _coerce_id("42") == 42
    for bad in (True, False):
        with pytest.raises(ValueError):
            _coerce_id(bad)


# The handlers themselves: a JSON true/false as an id is refused before the
# provider is touched. (This replaced an AST check that looked for the
# isinstance(..., bool) text; it now runs the handler.)

@pytest.mark.parametrize("bad", [True, False])
def test_handlers_refuse_a_bool_as_an_id(bad):
    from unittest.mock import MagicMock

    from mcp_server.tools.action_control.action_control_handler import ActionControlHandler
    from mcp_server.tools.variable_control.variable_control_handler import VariableControlHandler

    provider = MagicMock()
    var = VariableControlHandler(data_provider=provider, logger=logging.getLogger("t"))
    result = var.update(bad, "on")
    assert result["success"] is False and "integer" in result["error"]

    act = ActionControlHandler(data_provider=provider, logger=logging.getLogger("t"))
    result = act.execute(bad)
    assert result["success"] is False and "integer" in result["error"]

    # Nothing reached Indigo: no variable written, no action group run.
    assert provider.method_calls == [], provider.method_calls


def test_handlers_still_accept_a_real_id():
    from unittest.mock import MagicMock

    from mcp_server.tools.variable_control.variable_control_handler import VariableControlHandler

    provider = MagicMock()
    provider.get_variable.return_value = {"name": "v"}
    provider.update_variable.return_value = {"success": True, "previous": "a", "current": "b"}
    var = VariableControlHandler(data_provider=provider, logger=logging.getLogger("t"))
    var.update("42", "b")
    provider.update_variable.assert_called_once_with(42, "b")


def test_coerce_device_id_rejects_bool():
    # True/False are ints in Python; they must NOT pass as device ID 1/0.
    assert DeviceControlHandler._coerce_device_id(True) is None
    assert DeviceControlHandler._coerce_device_id(False) is None
    # Normal coercion still works.
    assert DeviceControlHandler._coerce_device_id("123") == 123
    assert DeviceControlHandler._coerce_device_id(456) == 456
    assert DeviceControlHandler._coerce_device_id("nope") == "nope"   # caller's int check rejects


# ── Indigo variables are strings, with Indigo's own conventions ──────────────

def test_variable_string_conversion_is_shared_and_correct():
    """create_variable used a bare str() and wrote "True"/"None".

    The update path normalised these in v2.10.1 and the create path was missed,
    so the two are now one helper.
    """
    from mcp_server.adapters.indigo_data_provider import _to_variable_string

    assert _to_variable_string(True) == "true"      # not "True"
    assert _to_variable_string(False) == "false"
    assert _to_variable_string(None) == ""          # not "None"
    assert _to_variable_string(21.5) == "21.5"
    assert _to_variable_string("on") == "on"


def test_bool_variable_stored_lowercase(monkeypatch):
    from mcp_server.adapters import indigo_data_provider as idp

    captured = {}

    class _Var:
        readOnly = False
        value = "x"

    class _Vars:
        def __contains__(self, k):
            return True
        def __getitem__(self, k):
            return _Var()

    class _Variable:
        @staticmethod
        def updateValue(vid, value=None):
            captured["value"] = value

    fake = type("_ind", (), {})()
    fake.variables = _Vars()
    fake.variable = _Variable
    monkeypatch.setattr(idp, "indigo", fake)

    p = idp.IndigoDataProvider(logger=logging.getLogger("t"))
    p.update_variable(123, True)
    assert captured["value"] == "true"        # not Python's "True"
    p.update_variable(123, False)
    assert captured["value"] == "false"
    p.update_variable(123, "KeepMe")
    assert captured["value"] == "KeepMe"


# ── Only ASCII digits are numbers (24-09-2026) ───────────────────────────────

@pytest.mark.parametrize("text", ["²", "١٢", "１２", "-²", "١.٥"])
def test_non_ascii_digits_are_left_as_sent(text):
    """str.isdigit() is True for all of these. "²" then raised inside int()
    (a -32603 with a traceback), and "١٢" silently became 12."""
    from mcp_server.common.arg_coercion import coerce_value
    assert coerce_value(text, {"integer", "number", "string"}) == text
    assert coerce_value(text, set()) == text


def test_ascii_digits_still_convert():
    from mcp_server.common.arg_coercion import coerce_value
    assert coerce_value("12", {"integer"}) == 12
    assert coerce_value("-1.5", {"number"}) == -1.5
