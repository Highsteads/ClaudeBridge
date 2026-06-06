#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    test_proxy_coerce.py
# Description: The stdio<->HTTP proxy's _coerce_args must coerce genuine
#              numbers/arrays but NEVER corrupt ordinary string args
#              ('true'/'null'/leading-zero codes/IPs).
# Author:      CliveS & Claude Opus 4.8
# Date:        06-06-2026
# Version:     1.0

import importlib.util
import os

import pytest

from conftest import SERVER_PLUGIN

_PROXY_PATH = os.path.join(SERVER_PLUGIN, "indigo_mcp_proxy.py")


def _load_proxy():
    spec = importlib.util.spec_from_file_location("cb_proxy_under_test", _PROXY_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


proxy = _load_proxy()
coerce = proxy._coerce_args


def test_plain_integer_coerced():
    assert coerce({"device_id": "12345678"}) == {"device_id": 12345678}


def test_negative_integer_coerced():
    assert coerce({"delta": "-5"}) == {"delta": -5}


def test_float_coerced():
    assert coerce({"setpoint": "21.5"}) == {"setpoint": 21.5}


def test_json_array_coerced():
    assert coerce({"ids": "[1, 2, 3]"}) == {"ids": [1, 2, 3]}


@pytest.mark.parametrize("val", ["true", "false", "null"])
def test_boolean_and_null_words_left_as_strings(val):
    # A variable value of "true"/"null" must reach the server intact.
    assert coerce({"value": val}) == {"value": val}


def test_leading_zero_code_left_as_string():
    assert coerce({"code": "0123"}) == {"code": "0123"}


def test_ip_address_left_as_string():
    assert coerce({"host": "192.168.4.71"}) == {"host": "192.168.4.71"}


def test_plus_prefixed_left_as_string():
    assert coerce({"x": "+5"}) == {"x": "+5"}


def test_double_dash_does_not_crash():
    # The historical "--5" crash: must not raise, must stay a string.
    assert coerce({"x": "--5"}) == {"x": "--5"}


def test_ordinary_word_left_as_string():
    assert coerce({"name": "Kitchen Lamp"}) == {"name": "Kitchen Lamp"}
