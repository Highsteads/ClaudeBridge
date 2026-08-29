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
