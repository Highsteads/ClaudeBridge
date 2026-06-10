#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    test_color_names.py
# Description: Behavioural tests for parse_color (the set_color tool's hex /
#              CSS-name resolver added in v2.7.2) — hex long and short forms,
#              named colours incl. British grey spellings, normalisation, and
#              the helpful ValueError on rubbish input.
# Author:      CliveS & Claude Fable 5
# Date:        10-06-2026
# Version:     1.0

import pytest

from mcp_server.tools.device_control.color_names import CSS_COLORS, parse_color


# ── Hex forms ─────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("value,expected", [
    ("#FF8000", (255, 128, 0)),
    ("ff8000",  (255, 128, 0)),     # leading # optional, case-insensitive
    ("#F80",    (255, 136, 0)),     # 3-digit shorthand: nibbles doubled
    ("#000000", (0, 0, 0)),
    ("#ffffff", (255, 255, 255)),
    # A bare 6-char string of hex digits is treated as hex by design — even
    # when it happens to spell a word ("facade" → fa/ca/de).
    ("facade",  (0xFA, 0xCA, 0xDE)),
])
def test_hex_parsing(value, expected):
    assert parse_color(value) == expected


@pytest.mark.parametrize("value", ["#FF80", "#GGHHII", "#12345", "#1234567"])
def test_invalid_hex_raises_with_guidance(value):
    with pytest.raises(ValueError) as exc:
        parse_color(value)
    assert "hex" in str(exc.value).lower()


# ── Named colours ─────────────────────────────────────────────────────────────

@pytest.mark.parametrize("value,expected", [
    ("tomato",       (255, 99, 71)),
    ("dodgerblue",   (30, 144, 255)),
    ("DodgerBlue",   (30, 144, 255)),    # case-insensitive
    ("dodger blue",  (30, 144, 255)),    # spaces ignored
    ("dodger_blue",  (30, 144, 255)),    # underscores ignored
    ("  tomato  ",   (255, 99, 71)),     # surrounding whitespace stripped
])
def test_named_colours(value, expected):
    assert parse_color(value) == expected


def test_british_grey_spellings_resolve_identically():
    for brit, us in [("grey", "gray"), ("darkgrey", "darkgray"),
                     ("dimgrey", "dimgray"), ("lightgrey", "lightgray"),
                     ("slategrey", "slategray")]:
        assert parse_color(brit) == parse_color(us)


def test_table_is_complete_and_well_formed():
    # 148 CSS4/X11 names, every channel an int in 0-255.
    assert len(CSS_COLORS) == 148
    for name, rgb in CSS_COLORS.items():
        assert name == name.lower()
        assert len(rgb) == 3
        assert all(isinstance(c, int) and 0 <= c <= 255 for c in rgb)


# ── Rubbish input ─────────────────────────────────────────────────────────────

@pytest.mark.parametrize("value", ["notacolour", "bleurgh", "rgb(1,2,3)"])
def test_unknown_name_raises_with_suggestion(value):
    with pytest.raises(ValueError) as exc:
        parse_color(value)
    assert "dodgerblue" in str(exc.value)    # the error teaches the format


@pytest.mark.parametrize("value", [None, "", "   "])
def test_empty_input_raises(value):
    with pytest.raises(ValueError):
        parse_color(value)
