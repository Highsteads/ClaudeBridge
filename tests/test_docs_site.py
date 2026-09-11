#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    test_docs_site.py
# Description: The documentation site (docs/, GitHub Pages) and the README
#              front page stay in step with the plugin and with each other:
#              the README's "What's new" is the head of docs/changelog.md,
#              verbatim; every page the bundle ships has a page of notes and
#              the notes index lists it; every doc carries the front matter
#              the theme needs; every local link and image resolves; the
#              site config points at this repository; and the README says
#              where the site is. Nothing here can name a house.
# Author:      CliveS & Claude Fable 5.1
# Date:        11-09-2026
# Version:     1.0

import re
import subprocess
from pathlib import Path

import pytest

ROOT      = Path(__file__).resolve().parents[1]
README    = ROOT / "README.md"
DOCS      = ROOT / "docs"
CHANGELOG = DOCS / "changelog.md"
SITE_URL  = "https://highsteads.github.io/ClaudeBridge/"

# A version-stamped entry: "### 2.26.0 (2026-09-10)", at the start of a line.
_ENTRY_RE = re.compile(r"^### (\d+(?:\.\d+)+) \(", re.M)


def _entries(text):
    """[(version, body)] in document order, body whitespace-normalised."""
    hits = list(_ENTRY_RE.finditer(text))
    out = []
    for i, m in enumerate(hits):
        end = hits[i + 1].start() if i + 1 < len(hits) else len(text)
        out.append((m.group(1), " ".join(text[m.start():end].split())))
    return out


def _section(text, heading):
    """The body of `## heading` up to the next heading of the same or a higher level."""
    m = re.search(r"^##\s+" + re.escape(heading) + r"\s*$", text, re.M)
    assert m, f"README has no '## {heading}' section"
    rest = text[m.end():]
    nxt = re.search(r"^#{1,2}\s+\S", rest, re.M)
    return rest[:nxt.start()] if nxt else rest


def _front_matter(path):
    text = path.read_text(encoding="utf-8")
    m = re.match(r"---\n(.*?)\n---\n", text, re.S)
    assert m, f"{path.relative_to(ROOT)}: no front matter"
    fm = {}
    for line in m.group(1).splitlines():
        if ":" in line:
            k, v = line.split(":", 1)
            fm[k.strip()] = v.strip()
    return fm, text[m.end():]


# ── the README and the changelog ────────────────────────────────────────

def test_whats_new_is_the_head_of_the_changelog_verbatim():
    """The README shows the newest few entries; the changelog holds them all.
    The two must not be allowed to drift by a word — a fix applied to one
    and not the other is exactly the kind of thing nobody notices."""
    readme = _entries(_section(README.read_text(encoding="utf-8"), "What's new"))
    full = _entries(CHANGELOG.read_text(encoding="utf-8"))
    assert 1 <= len(readme) <= 5, f"README What's new carries {len(readme)} entries; keep it short"
    assert len(full) > 50, "the changelog lost its history"   # 70 entries on 11-09-2026
    assert [v for v, _ in readme] == [v for v, _ in full[:len(readme)]], (
        f"README What's new versions {[v for v, _ in readme]} are not the head of the changelog "
        f"{[v for v, _ in full[:len(readme)]]}")
    for (v, a), (_, b) in zip(readme, full):
        assert a == b, f"entry {v} differs between README and docs/changelog.md"


def test_changelog_is_newest_first_and_never_repeats():
    versions = [tuple(int(x) for x in v.split(".")) for v, _ in _entries(CHANGELOG.read_text(encoding="utf-8"))]
    assert versions == sorted(versions, reverse=True), "changelog entries are not newest-first"
    assert len(versions) == len(set(versions)), "a version appears twice in the changelog"


def test_readme_points_at_the_site_and_the_site_at_the_repo():
    readme = README.read_text(encoding="utf-8")
    assert SITE_URL in readme, "README does not link to the documentation site"
    cfg = (DOCS / "_config.yml").read_text(encoding="utf-8")
    assert re.search(r"^baseurl:\s*/ClaudeBridge\s*$", cfg, re.M), "docs/_config.yml baseurl must be /ClaudeBridge"
    assert re.search(r"^url:\s*https://highsteads\.github\.io\s*$", cfg, re.M)
    assert re.search(r"^remote_theme:\s*\S+", cfg, re.M), "no theme declared"
    assert "github.com/Highsteads/ClaudeBridge" in cfg


# ── front matter ─────────────────────────────────────────────────────────

def test_every_doc_has_the_front_matter_the_theme_needs():
    docs = sorted(DOCS.rglob("*.md"))
    assert len(docs) >= 10, len(docs)
    orders = []
    for path in docs:
        fm, body = _front_matter(path)
        assert fm.get("title"), f"{path.relative_to(ROOT)}: no title"
        assert body.lstrip().startswith("# "), f"{path.relative_to(ROOT)}: body must open with a heading"
        assert fm.get("nav_order", "").isdigit(), f"{path.relative_to(ROOT)}: nav_order"
        orders.append(fm["nav_order"])
    assert len(orders) == len(set(orders)), "two pages share a nav_order"


def test_the_tool_reference_carries_the_generated_table():
    """docs/tools.md is the generator's target; the markers must be there and
    filled (the generator's own --check, run by test_version_consistency,
    proves the CONTENT is current)."""
    text = (DOCS / "tools.md").read_text(encoding="utf-8")
    assert "<!-- BEGIN TOOL TABLE -->" in text and "<!-- END TOOL TABLE -->" in text
    inner = text.split("<!-- BEGIN TOOL TABLE -->")[1].split("<!-- END TOOL TABLE -->")[0]
    assert inner.count("| `") >= 100, "the table has not been generated into docs/tools.md"
    assert "### Read tools (" in inner and "### Admin tools (" in inner


# ── links and images resolve ────────────────────────────────────────────

_LINK_RE = re.compile(r"\]\(([^)\s]+)\)|src=\"([^\"]+)\"")


def _local_targets(path):
    for m in _LINK_RE.finditer(path.read_text(encoding="utf-8")):
        target = m.group(1) or m.group(2)
        if re.match(r"^(https?:|mailto:|#)", target):
            continue
        yield target.split("#", 1)[0]


def _published():
    """What git TRACKS, as repo-relative paths — plus every directory above a
    tracked file, so a link to a folder resolves too. The working tree is not
    the site: docs/claude.md existed locally, resolved every link, and was
    never in the repository at all — `**/CLAUDE.md` in .gitignore swallowed it
    on a case-insensitive volume — so CI, and the published site, had a hole
    the local run could not see (11-09-2026). Falls back to the file system
    when there is no repository (a bare export)."""
    try:
        out = subprocess.run(["git", "ls-files", "-z"], cwd=ROOT, capture_output=True, check=True)
        files = {n for n in out.stdout.decode("utf-8").split("\0") if n}
    except (subprocess.CalledProcessError, OSError):
        return None
    dirs = set()
    for f in files:
        parts = f.split("/")
        for i in range(1, len(parts)):
            dirs.add("/".join(parts[:i]))
    return files | dirs


PUBLISHED = _published()


def _resolves(path, target):
    full = (path.parent / target).resolve()
    if PUBLISHED is None:
        return full.exists()
    try:
        rel = full.relative_to(ROOT.resolve())
    except ValueError:
        return False
    return str(rel) in PUBLISHED


@pytest.mark.parametrize("path", [README] + sorted(DOCS.rglob("*.md")), ids=lambda p: str(p.relative_to(ROOT)))
def test_every_local_link_and_image_resolves(path):
    """Against the TRACKED tree: a file that is only in the working copy is not
    on the site. Stage new docs before running the gate."""
    bad = [t for t in _local_targets(path) if t and not _resolves(path, t)]
    assert not bad, f"{path.relative_to(ROOT)}: local links to nothing git tracks {bad}"


def test_the_published_set_was_read():
    assert PUBLISHED is None or len(PUBLISHED) > 100


def test_the_link_scan_is_not_vacuous():
    assert sum(1 for _ in _local_targets(DOCS / "index.md")) >= 8
