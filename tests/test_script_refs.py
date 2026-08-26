#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    test_script_refs.py
# Description: Tests for the shared script-folder scanner (common/script_refs.py)
#              that backs dependency_map, audit_variables and
#              find_automation_references.
# Author:      CliveS & Claude Opus 5
# Date:        26-08-2026
# Version:     1.0

import pytest

from mcp_server.common.script_refs import (
    find_script_references,
    iter_script_files,
    scan_scripts_for_ids,
)

DEV_ID = 367205956


@pytest.fixture()
def folders(tmp_path):
    """Two sibling script folders, mirroring a real Indigo install."""
    scripts = tmp_path / "Scripts"
    python_scripts = tmp_path / "Python Scripts"
    scripts.mkdir()
    python_scripts.mkdir()

    (python_scripts / "Kitchen_Lights_Off.py").write_text(
        "DEVICE_IDS = {\n"
        '    "kitchen_spot_lights"    : 367205956,\n'
        "}\n"
        "indigo.device.turnOff(367205956)\n",
        encoding="utf-8",
    )
    (python_scripts / "By_Name.py").write_text(
        'dev = indigo.devices["Kitchen Spot Lights"]\n'
        "# Kitchen Spot Lights mentioned unquoted in prose only\n",
        encoding="utf-8",
    )
    (python_scripts / "Unrelated.py").write_text(
        "# a longer number that merely contains the ID\n"
        "OTHER = 1367205956\n",
        encoding="utf-8",
    )
    (scripts / "proxy.py").write_text("x = 1\n", encoding="utf-8")
    (tmp_path / "Scripts" / "notes.txt").write_text("367205956\n", encoding="utf-8")
    return [str(scripts), str(python_scripts)]


def test_finds_id_with_line_numbers(folders):
    hits = {h["script"]: h for h in find_script_references(DEV_ID, None, folders)}
    assert "Python Scripts/Kitchen_Lights_Off.py" in hits
    hit = hits["Python Scripts/Kitchen_Lights_Off.py"]
    assert hit["lines"] == [2, 4]
    assert hit["matched_by"] == ["id"]


def test_longer_number_containing_the_id_is_not_a_match(folders):
    names = {h["script"] for h in find_script_references(DEV_ID, None, folders)}
    assert "Python Scripts/Unrelated.py" not in names


def test_quoted_name_matches_and_bare_prose_does_not(folders):
    hits = {h["script"]: h
            for h in find_script_references(DEV_ID, "Kitchen Spot Lights", folders)}
    hit = hits["Python Scripts/By_Name.py"]
    assert hit["matched_by"] == ["name"]
    # Line 1 is the quoted lookup; line 2 mentions it unquoted and must not match.
    assert hit["lines"] == [1]


def test_name_matching_is_off_when_no_name_given(folders):
    names = {h["script"] for h in find_script_references(DEV_ID, None, folders)}
    assert "Python Scripts/By_Name.py" not in names


def test_regex_metacharacters_in_a_name_are_escaped(tmp_path):
    d = tmp_path / "Python Scripts"
    d.mkdir()
    (d / "s.py").write_text('x = "Drive (Left) Motion"\n', encoding="utf-8")
    hits = find_script_references(1, "Drive (Left) Motion", [str(d)])
    assert len(hits) == 1


def test_only_py_files_are_read(folders):
    names = {n for n, _c in iter_script_files(folders)}
    assert "Scripts/notes.txt" not in names
    assert "Scripts/proxy.py" in names


def test_single_folder_names_are_unprefixed(folders):
    names = {n for n, _c in iter_script_files([folders[1]])}
    assert "Kitchen_Lights_Off.py" in names


def test_missing_folder_is_tolerated(folders, tmp_path):
    hits = find_script_references(
        DEV_ID, None, folders + [str(tmp_path / "Nope")])
    assert any(h["script"].endswith("Kitchen_Lights_Off.py") for h in hits)


def test_bulk_scan_still_maps_ids_to_scripts(folders):
    id_map = scan_scripts_for_ids(folders)
    assert "Python Scripts/Kitchen_Lights_Off.py" in id_map[DEV_ID]
    assert 1367205956 in id_map
