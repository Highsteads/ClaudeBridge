#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    test_parse_ram.py
# Description: Tests for _parse_ram() — the RAM summary behind system_health.
# Author:      CliveS & Claude Opus 5
# Date:        25-07-2026
# Version:     1.0
#
# Regression cover for the 25-Jul-2026 bug: total RAM was derived by summing
# vm_stat's free/active/inactive/wired buckets, which omits compressed memory.
# On an 8 GB Mac under load that reported 4.4 GB, and it drifted further the
# busier the machine got. Total now comes from hw.memsize.

import os

import pytest

from mcp_server.tools.system_tools import system_tools_handler as sth


GIB = 1_073_741_824
PAGE = 16384          # Apple Silicon
MEMSIZE = 8 * GIB     # the Indigo Mac mini M2

# Real vm_stat capture from the Indigo Mac, 25-Jul-2026. The compressor bucket
# alone is 180,755 pages (2.76 GB) — the whole of what the old code lost.
VM_STAT = """Mach Virtual Memory Statistics: (page size of 16384 bytes)
Pages free:                                     5282.
Pages active:                                 106402.
Pages inactive:                               105551.
Pages speculative:                               205.
Pages throttled:                                   0.
Pages wired down:                              93892.
Pages purgeable:                                   2.
"Translation faults":                       39466710.
Pages copy-on-write:                         1458782.
Pages zero filled:                          17196116.
Pages reactivated:                            9140793.
File-backed pages:                             68004.
Anonymous pages:                              144154.
Pages stored in compressor:                   376320.
Pages occupied by compressor:                 180755.
Decompressions:                               5604274.
Compressions:                                 6605329.
Pageins:                                      2463612.
"""


@pytest.fixture
def fake_run(monkeypatch):
    """Stub _run() so tests never touch the real machine. Returns a setter
    taking (vm_stat_output, memsize_output)."""
    def _install(vm_stat=VM_STAT, memsize=str(MEMSIZE)):
        def _fake(cmd, timeout=5):
            # Match on the basename — the module calls these by absolute path.
            name = os.path.basename(cmd[0]) if cmd else ""
            if name == "vm_stat":
                return vm_stat
            if name == "sysctl":
                return memsize
            return ""
        monkeypatch.setattr(sth, "_run", _fake)
    return _install


# ── Headline behaviour ───────────────────────────────────────────────────────

def test_total_is_installed_ram_not_a_page_sum(fake_run):
    """The bug: total read 4.4 GB on an 8 GB machine."""
    fake_run()
    assert sth._parse_ram()["total_gb"] == 8.0


def test_old_page_sum_would_have_been_short(fake_run):
    """Guard the reasoning, not just the number — free+active+inactive+wired
    falls 3.3 GB short of installed RAM on this capture, and the compressor
    bucket it ignores accounts for most of that."""
    fake_run()
    old_total = (5282 + 106402 + 105551 + 93892) * PAGE
    assert round(old_total / GIB, 1) == 4.7
    assert round((MEMSIZE - old_total) / GIB, 1) == 3.3
    assert round(180755 * PAGE / GIB, 1) == 2.8


def test_used_follows_activity_monitor_formula(fake_run):
    """used = (anonymous - purgeable) + wired + compressed."""
    fake_run()
    expected = ((144154 - 2) + 93892 + 180755) * PAGE
    assert sth._parse_ram()["used_gb"] == round(expected / GIB, 1)


def test_free_is_available_not_the_free_list(fake_run):
    """'Pages free' alone was 0.08 GB and read as a machine at death's door."""
    fake_run()
    ram = sth._parse_ram()
    assert ram["free_gb"] > 1.0
    assert ram["free_gb"] != round(5282 * PAGE / GIB, 1)


def test_used_and_free_account_for_the_total(fake_run):
    fake_run()
    ram = sth._parse_ram()
    assert ram["used_gb"] + ram["free_gb"] == pytest.approx(ram["total_gb"], abs=0.1)


def test_used_pct_matches_used_over_total(fake_run):
    fake_run()
    ram = sth._parse_ram()
    assert ram["used_pct"] == pytest.approx(
        ram["used_gb"] / ram["total_gb"] * 100, abs=0.5
    )


# ── Page size ────────────────────────────────────────────────────────────────

def test_page_size_read_from_header_not_assumed(fake_run):
    """The 4096 default is wrong for every Apple Silicon Mac. If the header
    parse ever regresses, totals quarter — so pin it."""
    fake_run(vm_stat=VM_STAT.replace("page size of 16384", "page size of 4096"),
             memsize="")
    small = sth._parse_ram()
    fake_run(memsize="")
    large = sth._parse_ram()
    assert large["total_gb"] == pytest.approx(small["total_gb"] * 4, abs=0.2)


# ── Binary resolution ────────────────────────────────────────────────────────

def test_binaries_are_called_by_absolute_path(monkeypatch):
    """Indigo's plugin-host PATH omits /usr/sbin, so a bare "sysctl" raises
    FileNotFoundError, _run() swallows it, and the total silently falls back to
    the estimate. That shipped in 2.16.1 and read 7.5 GB on an 8 GB Mac. Pin
    every binary this module shells out to."""
    seen = []

    def _fake(cmd, timeout=5):
        seen.append(cmd[0])
        return VM_STAT if cmd[0].endswith("vm_stat") else str(MEMSIZE)

    monkeypatch.setattr(sth, "_run", _fake)
    sth._parse_ram()

    assert seen, "no binary was invoked"
    for path in seen:
        assert path.startswith("/"), f"{path!r} is a bare name — will fail in the plugin host"


def test_bin_falls_back_to_bare_name_when_path_missing():
    """A future macOS that moves a binary should degrade to PATH lookup, not
    hand subprocess a path that certainly does not exist."""
    assert sth._bin("/usr/bin/vm_stat") == "/usr/bin/vm_stat"
    assert sth._bin("/nowhere/at/all/sysctl") == "sysctl"


# ── Degradation ──────────────────────────────────────────────────────────────

def test_falls_back_to_page_sum_when_sysctl_unavailable(fake_run):
    """No hw.memsize — estimate from pages WITH the compressor. It lands at
    7.5 of 8 GB rather than the old 4.7: vm_stat never accounts for the ~0.5 GB
    the kernel and firmware reserve, so this is explicitly an estimate. Close
    enough to be useful, and no longer wrong by a third."""
    fake_run(memsize="")
    ram = sth._parse_ram()
    assert ram["total_gb"] == pytest.approx(7.5, abs=0.1)
    assert ram["total_gb"] > 4.7 * 1.5


def test_non_numeric_memsize_does_not_raise(fake_run):
    fake_run(memsize="not a number")
    assert sth._parse_ram()["total_gb"] == pytest.approx(7.5, abs=0.1)


def test_empty_vm_stat_returns_zeros_without_raising(fake_run):
    fake_run(vm_stat="", memsize="")
    ram = sth._parse_ram()
    assert ram["total_gb"] == 0.0
    assert ram["used_pct"] == 0.0


def test_garbage_vm_stat_returns_zeros_without_raising(fake_run):
    fake_run(vm_stat="wharrgarbl\nnot: a number.\n", memsize="")
    assert sth._parse_ram()["total_gb"] == 0.0


def test_used_never_exceeds_total(fake_run):
    """A tiny reported total must not produce negative free."""
    fake_run(memsize=str(1 * GIB))
    ram = sth._parse_ram()
    assert ram["used_gb"] <= ram["total_gb"]
    assert ram["free_gb"] >= 0.0
