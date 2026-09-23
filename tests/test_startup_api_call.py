#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    test_startup_api_call.py
# Description: A Claude Bridge start must not spend money. The Anthropic key
#              is checked only when InfluxDB (the one feature that uses it) is
#              on, or when the user presses Test Connections — and then with
#              a model listing, which costs no tokens.
# Author:      CliveS & Claude Opus 5.5
# Date:        23-09-2026
# Version:     1.0
#
# plugin.py needs a full Indigo host to import, so the method is lifted out of
# the source with ast and RUN against a stand-in anthropic module.

import ast
import logging
import os
from types import SimpleNamespace
from unittest.mock import MagicMock

from conftest import SERVER_PLUGIN


def _test_connections():
    with open(os.path.join(SERVER_PLUGIN, "plugin.py"), encoding="utf-8") as fh:
        tree = ast.parse(fh.read())
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.FunctionDef) and n.name == "test_connections")
    anthropic = MagicMock()
    ns = {"anthropic": anthropic}
    exec(compile(ast.Module(body=[fn], type_ignores=[]), "plugin.py", "exec"), ns)
    return ns["test_connections"], anthropic


def _self(**kw):
    base = dict(anthropic_api_key="sk-test", enable_influxdb=False,
                small_model="claude-haiku-4-5-20251001", logger=logging.getLogger("t"))
    base.update(kw)
    return SimpleNamespace(**base)


def test_start_with_influx_off_makes_no_api_call():
    fn, anthropic = _test_connections()
    assert fn(_self()) is True
    anthropic.Anthropic.assert_not_called()


def test_influx_on_checks_the_key_without_spending_tokens():
    fn, anthropic = _test_connections()
    client = anthropic.Anthropic.return_value
    fn(_self(enable_influxdb=True, influx_url="", influx_port=""))
    client.models.list.assert_called_once()
    client.messages.create.assert_not_called()


def test_the_button_checks_the_key_even_with_influx_off():
    fn, anthropic = _test_connections()
    client = anthropic.Anthropic.return_value
    assert fn(_self(), include_anthropic=True) is True
    client.models.list.assert_called_once()
