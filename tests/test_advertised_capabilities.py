#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    test_advertised_capabilities.py
# Description: The server must not advertise a capability it cannot honour.
#              Pins the initialize capabilities against what the handler
#              actually implements (ClaudeBridge v2.24.3).
# Author:      CliveS & Claude Opus 5
# Date:        30-08-2026
# Version:     1.0
#
# There is no push channel to a client: IWS answers one request with one
# response, and the SSE path is a buffered body built inside a single call.
# So `listChanged` can never be sent and `logging` can never be honoured.
# Advertising them cost real time — a client told it will be notified when the
# tool list changes has no reason to re-read it, which is why a session
# connected before the delete gate shipped went on stripping the new `confirm`
# argument while the plugin refused calls that were correctly made.

import io
import re

import pytest

from mcp_server import mcp_handler

# Read the module the tests just imported, so this always inspects the file
# that is actually deployed rather than a path guessed from the repo layout.
HANDLER_SRC = mcp_handler.__file__


def _source():
    with io.open(HANDLER_SRC, encoding="utf-8") as fh:
        return fh.read()


def _advertised():
    """The capabilities dict from the initialize response, as source text."""
    src = _source()
    match = re.search(r'"capabilities": \{(.*?)\n                    \}', src, re.S)
    assert match, "could not find the initialize capabilities block"
    return match.group(1)


def test_no_listchanged_is_advertised():
    """Never claim a notification with no channel to send it on."""
    assert "listChanged" not in _advertised(), (
        "listChanged is advertised again — this server has no push channel, so "
        "the notification can never be sent. Add a real channel first, or leave "
        "the claim out.")


def test_no_logging_capability_is_advertised():
    """`logging` means server-initiated messages plus logging/setLevel."""
    advertised = _advertised()
    assert '"logging"' not in advertised, (
        "logging is advertised, but logging/setLevel is not implemented and "
        "there is no channel for server-initiated log notifications")


def test_subscribe_false_is_kept():
    """An accurate negative declaration is worth stating."""
    assert '"subscribe": False' in _advertised()


def test_advertised_capabilities_have_handlers():
    """Every advertised capability must map to a method the handler serves."""
    src = _source()
    served = set(re.findall(r'method == "([a-z/]+)"', src))
    advertised = _advertised()
    required = {
        "prompts":   {"prompts/list", "prompts/get"},
        "resources": {"resources/list", "resources/read"},
        "tools":     {"tools/list", "tools/call"},
    }
    for name, methods in required.items():
        if f'"{name}"' in advertised:
            missing = methods - served
            assert not missing, f"advertises '{name}' but does not serve {sorted(missing)}"


@pytest.mark.parametrize("capability", ["prompts", "resources", "tools"])
def test_the_three_real_capabilities_are_still_advertised(capability):
    """The fix removes false claims — it must not remove true ones."""
    assert f'"{capability}"' in _advertised()
