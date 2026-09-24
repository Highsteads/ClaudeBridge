#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    test_device_credentials.py
# Description: Device props leave the plugin with credentials masked. Email+
#              keeps the SMTP password in serverPassword and UniFiHealth the
#              controller password in password, both secure="true" in their
#              Devices.xml, and every read-scope device tool returned them in
#              clear through dict(dev) — in pluginProps, ownerProps AND every
#              plugin's block of globalProps.
# Author:      CliveS & Claude Opus 5.5
# Date:        24-09-2026
# Version:     1.0

import os

import pytest

from mcp_server.common import device_props as dp

MAILER = "com.example.mailer"


class _Dev:
    """dict(dev) gives what Indigo's device gives: all the prop blocks."""

    def __init__(self, props):
        self.pluginId = MAILER
        self.globalProps = {MAILER: dict(props), "com.other": {"apiToken": "abc123xyz"}}
        self.pluginProps = {}
        self.ownerProps = dict(props)
        self.address = ""

    def keys(self):
        return ["id", "name", "pluginId", "globalProps", "ownerProps", "pluginProps"]

    def __getitem__(self, key):
        return {"id": 5, "name": "SMTP", "pluginId": self.pluginId}.get(key, getattr(self, key, None))


@pytest.fixture()
def plugins_dir(tmp_path, monkeypatch):
    bundle = tmp_path / "Mailer.indigoPlugin" / "Contents"
    (bundle / "Server Plugin").mkdir(parents=True)
    (bundle / "Info.plist").write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n<plist version="1.0"><dict>'
        f'<key>CFBundleIdentifier</key><string>{MAILER}</string></dict></plist>')
    (bundle / "Server Plugin" / "Devices.xml").write_text(
        '<Devices><Device id="smtp"><ConfigUI>'
        '<Field id="hostPort" type="textfield"/>'
        '<Field id="smtpSecretSauce" type="textfield"/>'
        '<Field id="relayWord" type="textfield" secure="true"/>'
        '</ConfigUI></Device></Devices>')
    monkeypatch.setattr(dp, "PLUGINS_DIR_OVERRIDE", str(tmp_path))
    monkeypatch.setattr(dp, "_PLUGIN_SCAN_AT", 0.0)
    dp._DEVICES_XML_BY_PLUGIN.clear()
    dp._SECURE_BY_PATH.clear()
    return tmp_path


PROPS = {"hostPort": "587", "serverPassword": "hunter2!", "relayWord": "opensesame",
         "serverLogin": "me@example.com", "wifiPsk": "longpsk99", "ignored": True,
         "pinTimeout": ""}


def test_every_props_block_is_masked(plugins_dir):
    data = dp.device_dict(_Dev(PROPS))
    for block in (data["ownerProps"], data["pluginProps"], data["globalProps"][MAILER]):
        assert block["serverPassword"] == dp.MASK, "credential by name"
        assert block["relayWord"] == dp.MASK, "secure=\"true\" in Devices.xml"
        assert block["wifiPsk"] == dp.MASK, "local extra: psk"
        assert block["hostPort"] == "587" and block["serverLogin"] == "me@example.com"
        assert block["ignored"] is True and block["pinTimeout"] == "", "nothing to hide"
    assert data["globalProps"]["com.other"]["apiToken"] == dp.MASK


def test_no_secret_value_survives_anywhere_in_the_reply(plugins_dir):
    text = repr(dp.device_dict(_Dev(PROPS)))
    for secret in ("hunter2!", "opensesame", "longpsk99", "abc123xyz"):
        assert secret not in text


def test_a_broken_devices_xml_still_masks_by_name(plugins_dir):
    xml = plugins_dir / "Mailer.indigoPlugin" / "Contents" / "Server Plugin" / "Devices.xml"
    xml.write_text("<Devices><not closed")
    os.utime(xml, (1, 1))
    data = dp.device_dict(_Dev(PROPS))
    assert data["ownerProps"]["serverPassword"] == dp.MASK
    assert data["ownerProps"]["relayWord"] == "opensesame", "secure list unavailable: name only"


def test_get_devices_by_type_is_slim_unless_full_is_asked_for():
    from mcp_server.tools.get_devices_by_type.main import GetDevicesByTypeHandler

    class _Provider:
        def get_all_devices_unfiltered(self):
            return [{"id": 1, "name": "Lamp", "class": "indigo.DimmerDevice",
                     "deviceTypeId": "", "ownerProps": {"x": 1}, "globalProps": {"p": {}}}]

    h = GetDevicesByTypeHandler(_Provider())
    slim = h.get_devices("dimmer")
    assert slim["detail"] == "slim" and "ownerProps" not in slim["devices"][0]
    full = h.get_devices("dimmer", detail="full")
    assert "ownerProps" in full["devices"][0]
