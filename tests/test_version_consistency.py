#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    test_version_consistency.py
# Description: Fails when the released version signals disagree — Info.plist,
#              the README header line, and the README changelog.
# Author:      CliveS & Claude Opus 5
# Date:        29-08-2026
# Version:     1.0
#
# The README header sat at 2.17.1 while the plugin shipped 2.23.0 — six
# releases, with the changelog underneath it correct the whole time. Nothing
# owned the header line, so nothing caught it. A user reading the top of the
# page was told the wrong version for three months.

import os
import plistlib
import re
import subprocess
import sys

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PLIST = os.path.join(REPO, "Claude Bridge.indigoPlugin", "Contents", "Info.plist")
README = os.path.join(REPO, "README.md")

pytestmark = pytest.mark.skipif(
    not (os.path.isfile(PLIST) and os.path.isfile(README)),
    reason="repo layout not present (running against an installed bundle only)",
)


def _plugin_version() -> str:
    with open(PLIST, "rb") as fh:
        return plistlib.load(fh)["PluginVersion"]


def _readme() -> str:
    with open(README, encoding="utf-8") as fh:
        return fh.read()


def test_plugin_version_is_digits_and_dots():
    """Indigo rejects anything else — '1.0.5b2' is called out as invalid."""
    assert re.fullmatch(r"\d+(\.\d+)*", _plugin_version())


def test_readme_header_matches_info_plist():
    match = re.search(r"^\*\*Version:\*\* (\S+)$", _readme(), re.M)
    assert match, "README lost its **Version:** header line"
    assert match.group(1) == _plugin_version()


def test_readme_changelog_leads_with_this_version():
    entries = re.findall(r"^### (\d+\.\d+\.\d+) \(", _readme(), re.M)
    assert entries, "README lost its changelog"
    assert entries[0] == _plugin_version(), (
        f"newest changelog entry is {entries[0]}, Info.plist says "
        f"{_plugin_version()} — every bump appends an entry")


def test_cfbundleversion_is_the_bundle_layout_not_the_release():
    """Jay: CFBundleVersion describes the bundle layout and stays at 1.0.0."""
    with open(PLIST, "rb") as fh:
        assert plistlib.load(fh)["CFBundleVersion"] == "1.0.0"


def test_generated_tool_table_is_current():
    """The README's tool table must match the code that generates it.

    `scripts/generate_tool_doc.py --check` already existed and nothing ran it,
    so the table could drift for as long as nobody happened to regenerate it.
    A tool whose description changed in the handler but not in the README is
    the same class of silent divergence as a stale version header.
    """
    script = os.path.join(REPO, "scripts", "generate_tool_doc.py")
    if not os.path.isfile(script):
        pytest.skip("doc generator not present")
    result = subprocess.run([sys.executable, script, "--check"],
                            cwd=REPO, capture_output=True, text=True)
    assert result.returncode == 0, (
        "README tool table is stale or a tool is unclassified — run "
        "`python3 scripts/generate_tool_doc.py --write`\n"
        + (result.stdout or "") + (result.stderr or ""))


def test_required_info_plist_keys_are_present():
    """Six required keys, per Indigo's Developer's Guide.

    CFBundleURLTypes is the one repeatedly missed — it becomes the plugin's
    "About [PLUGIN]" menu item, and the Plugin Store expects it.
    """
    with open(PLIST, "rb") as fh:
        keys = set(plistlib.load(fh))
    required = {"PluginVersion", "ServerApiVersion", "CFBundleDisplayName",
                "CFBundleIdentifier", "CFBundleVersion", "CFBundleURLTypes"}
    assert required <= keys, f"missing: {sorted(required - keys)}"


def test_cfbundleurltypes_has_the_shape_indigo_accepts():
    """Presence is not enough — the SHAPE is what Indigo validates.

    CFBundleURLTypes must be an array of dicts keyed CFBundleURLName. Written as a
    bare string the plist still parses, still contains the key, and still passes a
    presence check — but Indigo refuses the bundle at install with

        InstallPlugin() caught exception: LowLevelBadParameterError

    which names neither the key nor the file. Cost a failed install on 01-09-2026.
    """
    with open(PLIST, "rb") as handle:
        plist = plistlib.load(handle)
    entry = plist.get("CFBundleURLTypes")
    assert isinstance(entry, list), (
        f"CFBundleURLTypes must be an array, got {type(entry).__name__}")
    assert entry, "CFBundleURLTypes must not be empty"
    for item in entry:
        assert isinstance(item, dict), (
            f"each CFBundleURLTypes entry must be a dict, got {type(item).__name__}")
        assert item.get("CFBundleURLName"), "each entry needs a non-empty CFBundleURLName"
