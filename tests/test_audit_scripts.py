#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    test_audit_scripts.py
# Description: Regression — the audit tools must scan BOTH Indigo script folders
#              (Scripts AND Python Scripts). A previous version returned only the
#              first existing folder, so any device/variable ID used solely in
#              "Python Scripts" was invisible and reported as unreferenced.
# Author:      CliveS & Claude Opus 4.8
# Date:        09-06-2026
# Version:     1.0

import os

from mcp_server.tools.audit.audit_handler import (
    _iter_script_files,
    _scan_scripts_for_ids,
)


def _write(path, text):
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)


def test_scan_finds_ids_in_both_folders(tmp_path):
    """An ID present ONLY in 'Python Scripts' must still be found — the exact
    regression behind the documented audit_variables over-reporting."""
    scripts = tmp_path / "Scripts"
    python_scripts = tmp_path / "Python Scripts"
    scripts.mkdir()
    python_scripts.mkdir()

    # ID only in the (previously-skipped) Python Scripts folder.
    _write(python_scripts / "garage.py",
           "indigo.variable.updateValue(783424354, value='on')\n")
    # A different ID only in Scripts.
    _write(scripts / "direct.py",
           "dev = indigo.devices[123456789]\n")

    id_map = _scan_scripts_for_ids([str(scripts), str(python_scripts)])

    assert 783424354 in id_map, "ID in Python Scripts was not scanned"
    assert 123456789 in id_map, "ID in Scripts was not scanned"


def test_iter_prefixes_folder_when_both_present(tmp_path):
    """When both folders exist, file labels are folder-prefixed so a caller can
    tell a same-named file in each folder apart."""
    scripts = tmp_path / "Scripts"
    python_scripts = tmp_path / "Python Scripts"
    scripts.mkdir()
    python_scripts.mkdir()
    _write(scripts / "a.py", "x = 1\n")
    _write(python_scripts / "b.py", "y = 2\n")

    names = {n for n, _c in _iter_script_files([str(scripts), str(python_scripts)])}
    assert "Scripts/a.py" in names
    assert "Python Scripts/b.py" in names


def test_iter_single_dir_str_is_tolerated(tmp_path):
    """A bare folder string (not a list) must still work — backward compat."""
    scripts = tmp_path / "Scripts"
    scripts.mkdir()
    _write(scripts / "only.py", "z = 3\n")

    names = [n for n, _c in _iter_script_files(str(scripts))]
    # Single folder → no folder prefix.
    assert names == ["only.py"]


def test_scan_skips_non_python_and_missing_dirs(tmp_path):
    scripts = tmp_path / "Scripts"
    scripts.mkdir()
    _write(scripts / "note.txt", "987654321\n")          # not .py → ignored
    _write(scripts / "real.py", "v = indigo.variables[555444333]\n")
    missing = tmp_path / "Does Not Exist"

    id_map = _scan_scripts_for_ids([str(scripts), str(missing)])
    assert 555444333 in id_map
    assert 987654321 not in id_map      # .txt content must not be scanned
