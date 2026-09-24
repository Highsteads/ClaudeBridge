#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    test_sun_times.py
# Description: server_info's sunrise and sunset are for the SAME day. Called
#              with no argument, Indigo's calculateSunrise() returns the NEXT
#              sunrise, so after dawn "today" gave tomorrow's sunrise beside
#              today's sunset (measured live 24-09-2026).
# Author:      CliveS & Claude Opus 5.5
# Date:        24-09-2026
# Version:     1.0

import logging
from datetime import date, datetime, timedelta
from unittest.mock import MagicMock

from mcp_server.tools.extended_tools import extended_tools_handler as eth


def _handler(monkeypatch):
    fake = MagicMock()

    def _rise(d=None):   # mimics Indigo: no date -> the NEXT sunrise (tomorrow after dawn)
        day = d if d is not None else date.today() + timedelta(days=1)
        return datetime.combine(day, datetime.min.time()).replace(hour=7)

    def _set(d=None):
        day = d if d is not None else date.today()
        return datetime.combine(day, datetime.min.time()).replace(hour=19)

    fake.server.calculateSunrise.side_effect = _rise
    fake.server.calculateSunset.side_effect = _set
    monkeypatch.setattr(eth, "indigo", fake, raising=False)
    h = object.__new__(eth.ExtendedToolsHandler)
    h.logger = logging.getLogger("t")
    h.tool_name = "extended_tools"
    return h


def test_default_is_today_for_both(monkeypatch):
    h = _handler(monkeypatch)
    rise, sset = h.calculate_sunrise(), h.calculate_sunset()
    today = date.today().isoformat()
    assert rise["sunrise"].startswith(today) and sset["sunset"].startswith(today)
    assert rise["date"] == today


def test_an_explicit_date_is_used(monkeypatch):
    h = _handler(monkeypatch)
    assert h.calculate_sunrise("2026-12-21")["sunrise"].startswith("2026-12-21")
