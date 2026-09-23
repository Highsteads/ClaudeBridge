#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    test_folders.py
# Description: Folder deletes refuse a non-empty folder unless asked to cascade.
# Author:      CliveS & Claude Opus 5.5
# Date:        24-09-2026
# Version:     1.0
#
# Moved unchanged from the release-named files in the 3.0 spring clean:
#   test_v290_tools.py (v2.9.0)


import sys
import types
from unittest.mock import MagicMock

from mcp_server.tools.system_tools.system_tools_handler import SystemToolsHandler

from test_dispatch import _LOGGER


# ── folder delete semantics ───────────────────────────────────────────────────

class _FakeFolder:
    def __init__(self, fid, name):
        self.id, self.name = fid, name


def _fake_collection(monkeypatch, attr, folders, members):
    """Install a fake indigo.<devices|variables> with folders + iter()."""
    ind = sys.modules["indigo"]
    coll = types.SimpleNamespace()
    coll.folders = folders
    coll.iter = lambda: iter(members)
    coll.folder = MagicMock()
    monkeypatch.setattr(ind, attr, coll, raising=False)
    return coll


def test_delete_device_folder_refuses_non_empty(monkeypatch):
    member = types.SimpleNamespace(name="Lamp", folderId=7)
    coll = _fake_collection(monkeypatch, "devices", [_FakeFolder(7, "Spare")], [member])
    h = SystemToolsHandler(data_provider=MagicMock(), logger=_LOGGER)
    result = h.delete_device_folder("Spare")
    assert result["success"] is False and "refusing" in result["error"]
    assert result["members"] == ["Lamp"]
    coll.folder.delete.assert_not_called()


def test_delete_device_folder_deletes_empty_by_name_or_id(monkeypatch):
    coll = _fake_collection(monkeypatch, "devices", [_FakeFolder(7, "Spare")], [])
    h = SystemToolsHandler(data_provider=MagicMock(), logger=_LOGGER)
    result = h.delete_device_folder(7)
    assert result["success"] is True and result["deleted_children"] == 0
    args, kwargs = coll.folder.delete.call_args
    assert args[0].id == 7 and kwargs == {"deleteAllChildren": False}


def test_delete_variable_folder_cascades_only_when_asked(monkeypatch):
    member = types.SimpleNamespace(name="old_var", folderId=9)
    coll = _fake_collection(monkeypatch, "variables", [_FakeFolder(9, "Retired")], [member])
    h = SystemToolsHandler(data_provider=MagicMock(), logger=_LOGGER)
    result = h.delete_variable_folder("Retired", delete_children=True)
    assert result["success"] is True and result["deleted_children"] == 1
    coll.folder.delete.assert_called_once()
    assert coll.folder.delete.call_args.kwargs == {"deleteAllChildren": True}


def test_delete_folder_not_found(monkeypatch):
    _fake_collection(monkeypatch, "devices", [], [])
    h = SystemToolsHandler(data_provider=MagicMock(), logger=_LOGGER)
    assert h.delete_device_folder("NoSuch")["success"] is False
