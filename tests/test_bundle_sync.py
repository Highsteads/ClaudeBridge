#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    test_bundle_sync.py
# Description: The repo keeps two copies of the proxy and the secrets template:
#              one at the repo root (what install.py/install docs reference) and
#              one inside the plugin bundle (what ships). Sync between them is
#              manual — this test fails the suite the moment either copy is
#              edited alone, so a stale proxy can never ship silently.
# Author:      CliveS & Claude Fable 5
# Date:        10-06-2026
# Version:     1.0

import filecmp
import os

import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BUNDLE_SP = os.path.join(
    REPO_ROOT, "Claude Bridge.indigoPlugin", "Contents", "Server Plugin"
)

DUPLICATED_FILES = ["indigo_mcp_proxy.py", "IndigoSecrets_example.py"]


@pytest.mark.parametrize("filename", DUPLICATED_FILES)
def test_repo_root_copy_matches_bundle_copy(filename):
    root_copy   = os.path.join(REPO_ROOT, filename)
    bundle_copy = os.path.join(BUNDLE_SP, filename)
    assert os.path.isfile(root_copy), f"missing repo-root copy: {root_copy}"
    assert os.path.isfile(bundle_copy), f"missing bundle copy: {bundle_copy}"
    assert filecmp.cmp(root_copy, bundle_copy, shallow=False), (
        f"{filename} differs between the repo root and the bundle — "
        f"edit BOTH copies (the bundle is what ships; the root copy is what "
        f"install.py and the docs reference)."
    )
