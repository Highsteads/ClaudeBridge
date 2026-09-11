#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    test_no_private_strings.py
# Description: This repository is public. Nothing in it may carry a real
#              address, hostname or e-mail from any one house: every 192.168
#              address must be a documentation one (the .1 and .2 subnets, the
#              192.168.0.0/16 range literal the egress guard names, or the
#              made-up 192.168.77 subnet the egress tests use), every
#              *.indigodomo.net or *.ts.net host an obvious example, and every
#              e-mail an example.com one. The test names no real value — it
#              cannot, it is published too — so it refuses by SHAPE and reports
#              file:line for anything it will not accept. Copied from the
#              Dashboards repo (v1.1) with those two allowances.
# Author:      CliveS & Claude Fable 5.1
# Date:        11-09-2026
# Version:     1.1

import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TEXT = {".py", ".mjs", ".js", ".html", ".css", ".md", ".json", ".txt", ".yml", ".yaml",
        ".toml", ".sh", ".plist", ".xml"}
SKIP = {".git", "__pycache__", ".pytest_cache", ".ruff_cache", "Packages", "node_modules",
        "work", "drafts"}

IPV4  = re.compile(r"\b(\d{1,3})\.(\d{1,3})\.(\d{1,3})\.(\d{1,3})\b")
HOST  = re.compile(r"[A-Za-z0-9<>_-]+(?:\.[A-Za-z0-9<>_-]+)*\.(?:indigodomo\.net|ts\.net)\b")
EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")

ALLOWED_HOSTS = {"myhouse.indigodomo.net", "example.indigodomo.net", "your-reflector.indigodomo.net",
                 "your-reflector-url.indigodomo.net", "indigo.tail-example.ts.net", "<host>.<tailnet>.ts.net"}


def files():
    """The PUBLISHED files: what git tracks. A gitignored local note may hold
    anything; it is the tracked tree that reaches the world. Falls back to a
    walk when there is no repository (a bare export)."""
    try:
        out = subprocess.run(["git", "ls-files", "-z"], cwd=ROOT, capture_output=True, check=True)
        paths = [ROOT / n for n in out.stdout.decode("utf-8").split("\0") if n]
    except (subprocess.CalledProcessError, OSError):
        paths = list(ROOT.rglob("*"))
    for p in paths:
        if any(part in SKIP for part in p.relative_to(ROOT).parts):
            continue
        if p.is_file() and (p.suffix in TEXT or p.name == ".gitignore") and "min.js" not in p.name:
            yield p


def lines():
    for p in files():
        try:
            text = p.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for i, line in enumerate(text.splitlines(), 1):
            yield f"{p.relative_to(ROOT)}:{i}", line


def test_the_scan_saw_the_tree():
    assert sum(1 for _ in files()) > 100, "a glob that matches nothing passes everything"


def test_every_192_168_address_is_a_documentation_one():
    bad = []
    for where, line in lines():
        for m in IPV4.finditer(line):
            a, b, c, d = (int(x) for x in m.groups())
            # .0.0 is the RFC 1918 range literal in the egress guard; .77.x is the
            # invented subnet the egress tests use as a fixture. Neither is a house.
            if a == 192 and b == 168 and c not in (1, 2, 77) and not (c == 0 and d == 0):
                bad.append(f"{where}: {m.group(0)}")
    assert not bad, "real-looking LAN addresses (use 192.168.1.x / 192.168.2.x):\n" + "\n".join(bad)


def test_every_reflector_and_tailscale_host_is_an_example():
    bad = sorted({f"{where}: {h}" for where, line in lines()
                  for h in HOST.findall(line) if h.lower() not in ALLOWED_HOSTS})
    assert not bad, "hosts that look like a real house:\n" + "\n".join(bad)


def _is_email(candidate):
    """An e-mail, not a URL credential or a version pin: `user:pass@192.168.2.50`
    in an RTSP address has the shape but an all-numeric host, and is a fixture
    password the security test exists to redact — not an address of anyone's.
    `just-the-docs@v0.12.0` (a Jekyll remote-theme ref) has the shape and a
    domain whose last label is a number; a real address always ends in letters.
    Caught on CI, 11-09-2026, the first push after docs/_config.yml existed."""
    domain = candidate.rsplit("@", 1)[1]
    if IPV4.fullmatch(domain):
        return False
    return bool(re.fullmatch(r"[A-Za-z]{2,}", domain.rsplit(".", 1)[-1]))


def test_every_email_is_an_example():
    ok = ("@example.com", "@example.org", "@example.net")      # RFC 2606 reserved domains
    bad = sorted({f"{where}: {e}" for where, line in lines()
                  for e in EMAIL.findall(line)
                  if _is_email(e) and not e.lower().endswith(ok)})
    assert not bad, "e-mail addresses that are not example.com/org/net:\n" + "\n".join(bad)


def test_the_local_drafts_and_clones_stay_out():
    ignore = (ROOT / ".gitignore").read_text(encoding="utf-8")
    assert "/drafts/" in ignore and "/work/" in ignore
