#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    test_generate_tool_doc.py
# Description: scripts/generate_tool_doc.py owns every tool count written in
#              prose. These tests prove it rewrites each phrasing, keeps an
#              ASCII diagram's width, leaves history alone, and that --check
#              fails on a stale count and on one it cannot rewrite.
# Author:      CliveS & Claude Opus 5.5
# Date:        23-09-2026
# Version:     1.0

import importlib.util
import os
import shutil
import subprocess
import sys

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_spec = importlib.util.spec_from_file_location(
    "generate_tool_doc", os.path.join(_REPO, "scripts", "generate_tool_doc.py"))
gtd = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(gtd)

SCOPES = {"read": 28, "write": 21, "admin": 20}


def _rewrite(text, path="docs/page.md"):
    return gtd.rewrite_counts(path, text, 69, SCOPES)


def test_every_known_phrasing_is_rewritten():
    before = ("That gives Claude **159 tools** for reading. "
              "Claude Bridge gives Claude Code **168 MCP tools**, with **65 read** tools, "
              "**63 write** tools and **31 admin** tools. The 159 tools by what they do. "
              "You should see 159 `indigo-mcp` tools available. You should see 159 tools "
              "available. Access through 168 tools. On top of the 168 below. "
              "# handler modules (159 tools)")
    after = _rewrite(before)
    assert "159" not in after and "168" not in after
    assert "**69 tools**" in after and "**69 MCP tools**" in after
    assert "**28 read**" in after and "**21 write**" in after and "**20 admin**" in after
    assert gtd.stray_counts("docs/page.md", after, 69, SCOPES) == []


def test_an_unrelated_number_is_left_alone():
    text = "Port 8176 on 192.168.1.20, 85 of 1,576 calls ran over 10 s, 18 handler modules."
    assert _rewrite(text) == text


def test_the_diagram_keeps_its_width():
    line = "│  key automatically   │         │  (159 tools) │"
    out = _rewrite(line)
    assert out == "│  key automatically   │         │  (69 tools)  │"
    assert len(out) == len(line)


def test_whats_new_and_the_changelog_are_history():
    readme = ("## What's new\n\n### 3.0.0\nCut from 159 tools to 69: **159 tools** became "
              "**69 tools**.\n\n## What it does\n\nClaude gets **159 tools**.\n")
    out = _rewrite(readme, path=os.path.join(_REPO, "README.md"))
    assert "Cut from 159 tools to 69: **159 tools** became" in out, "history was rewritten"
    assert out.endswith("Claude gets **69 tools**.\n")
    assert gtd.stray_counts(os.path.join(_REPO, "README.md"), out, 69, SCOPES) == []
    assert not any(p.endswith("changelog.md") for p in gtd.count_files())


def test_a_phrasing_it_cannot_rewrite_is_reported_not_guessed():
    text = "There are 159 built-in tools."
    assert _rewrite(text) == text
    strays = gtd.stray_counts("docs/page.md", text, 69, SCOPES)
    assert len(strays) == 1 and "159 built-in tools" in strays[0]


def _run_check(repo_copy):
    return subprocess.run([sys.executable, os.path.join(repo_copy, "scripts",
                                                        "generate_tool_doc.py"), "--check"],
                          capture_output=True, text=True)


def _copy_repo(tmp_path):
    dst = tmp_path / "repo"
    for item in ("scripts", "docs", "README.md", "Claude Bridge.indigoPlugin"):
        src = os.path.join(_REPO, item)
        if os.path.isdir(src):
            shutil.copytree(src, dst / item, ignore=shutil.ignore_patterns("__pycache__"))
        else:
            dst.mkdir(parents=True, exist_ok=True)
            shutil.copy(src, dst / item)
    return str(dst)


def test_check_fails_on_a_stale_count_and_passes_once_written(tmp_path):
    repo = _copy_repo(tmp_path)
    assert _run_check(repo).returncode == 0
    cfg = os.path.join(repo, "docs", "_config.yml")
    with open(cfg, encoding="utf-8") as fh:
        text = fh.read()
    with open(cfg, "w", encoding="utf-8") as fh:
        fh.write(text.replace("through 69 tools", "through 70 tools"))
    failed = _run_check(repo)
    assert failed.returncode == 1 and "docs/_config.yml" in failed.stderr
    subprocess.run([sys.executable, os.path.join(repo, "scripts", "generate_tool_doc.py"),
                    "--write"], check=True, capture_output=True)
    assert _run_check(repo).returncode == 0


def test_check_fails_on_a_count_it_cannot_rewrite(tmp_path):
    repo = _copy_repo(tmp_path)
    page = os.path.join(repo, "docs", "index.md")
    with open(page, "a", encoding="utf-8") as fh:
        fh.write("\nAll 159 shiny tools are here.\n")
    failed = _run_check(repo)
    assert failed.returncode == 1 and "159 shiny tools" in failed.stderr
