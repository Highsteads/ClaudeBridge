#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    test_v284_fixes.py
# Description: Regressions for the v2.8.4 cleanup batch — device_id bool guard,
#              verify_ssl strict tri-state, boolean-variable lowercase storage,
#              and enable_device stringy-bool coercion.
# Author:      CliveS & Claude Opus 4.8
# Date:        09-06-2026
# Version:     1.0

import logging

from mcp_server.tools.device_control.device_control_handler import DeviceControlHandler


def test_coerce_device_id_rejects_bool():
    # True/False are ints in Python; they must NOT pass as device ID 1/0.
    assert DeviceControlHandler._coerce_device_id(True) is None
    assert DeviceControlHandler._coerce_device_id(False) is None
    # Normal coercion still works.
    assert DeviceControlHandler._coerce_device_id("123") == 123
    assert DeviceControlHandler._coerce_device_id(456) == 456
    assert DeviceControlHandler._coerce_device_id("nope") == "nope"   # caller's int check rejects


def test_verify_ssl_strict_tristate():
    from mcp_server.webhooks.subscription_manager import SubscriptionManager
    from mcp_server.security.egress_guard import Allowlist
    from mcp_server.tools.webhooks.webhook_handler import WebhookHandler

    def handler():
        mgr = SubscriptionManager()
        allow = Allowlist.from_entries(["8.8.8.8"])
        return WebhookHandler(mgr, allowlist_provider=lambda: allow,
                              enabled_provider=lambda: True), mgr

    # A real boolean False is the ONLY thing that disables verification.
    h, mgr = handler()
    h.create_subscription(webhook_url="https://8.8.8.8/h", entity_type="device",
                          conditions={"any_change": True}, verify_ssl=False)
    assert mgr.list_all()[0].verify_ssl is False

    # The string "false" must NOT disable it (would silently drop TLS checks).
    h, mgr = handler()
    h.create_subscription(webhook_url="https://8.8.8.8/h", entity_type="device",
                          conditions={"any_change": True}, verify_ssl="false")
    assert mgr.list_all()[0].verify_ssl is True

    # An empty string also defaults to verify.
    h, mgr = handler()
    h.create_subscription(webhook_url="https://8.8.8.8/h", entity_type="device",
                          conditions={"any_change": True}, verify_ssl="")
    assert mgr.list_all()[0].verify_ssl is True


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
