#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    test_zwave_replies.py
# Description: The Z-Wave tools read what Indigo really answers. Measured on
#              Indigo 2025.2 against a real Z-Wave controller on 19-11-2026:
#              a waited sendConfigParm (nodeId= form) and sendRaw answer
#              cmdSuccess, endpoint, nodeId and queuedForNextWake; an unwaited
#              one answers None; indigo.device.ping answers Success and
#              TimeDelta; and with Interfaces > Z-Wave turned off,
#              sendConfigParm, sendRaw, exitInclusionExclusionMode and
#              stopNetworkOptimize raise InterfaceError "interface Z-Wave is
#              not enabled" and send nothing. Until 3.9.2 the config tool read
#              only Success, so a waited set never reported its
#              acknowledgement, and a turned-off interface came back as a red
#              Error. Only that exact message is a refusal: any other
#              InterfaceError, a database driver's above all, stays an Error.
#
#              Guards and fixes: the tests marked "guard" held on 3.9.1 too
#              and pin behaviour that must not change; the rest failed there.
# Author:      CliveS & Claude Opus 5.5
# Date:        20-11-2026
# Version:     1.1

import logging
import sqlite3
import threading
import time
from types import SimpleNamespace

import pytest

from conftest import FakeIndigoDict, call_tool

LOG = logging.getLogger("test-zwave-replies")

# The reply SHAPES as Indigo gave them. The numbers are made up to match the
# fake device below (address "12"); only the keys and the flag values are the
# measured part.
WAITED_ON_ENDPOINT = {"cmdSuccess": True, "endpoint": 1, "nodeId": 12,
                      "queuedForNextWake": False}
WAITED_ON_ROOT     = {"cmdSuccess": True, "endpoint": None, "nodeId": 12,
                      "queuedForNextWake": False}
PING_REPLY         = {"Success": True, "TimeDelta": 16}
NOT_ENABLED        = "interface Z-Wave is not enabled"

# A neutral parameter: index 3, one byte, value 5.
PARAM = (3, 1, 5)


class InterfaceError(Exception):
    """Stands in for indigo.PluginBase.InterfaceError. Indigo's report names
    the class only, so the tools must recognise it by name."""


class _PluginBase:
    InterfaceError = InterfaceError


class _ZWave:
    """indigo.zwave: records each call, answers `reply`, or raises `error`."""

    def __init__(self, reply=None, error=None):
        self.calls, self.reply, self.error = [], reply, error

    def __getattr__(self, name):
        if name.startswith("__"):
            raise AttributeError(name)

        def _call(*args, **kwargs):
            self.calls.append((name, args, kwargs))
            if self.error is not None:
                raise self.error
            return self.reply
        return _call


class _Device:
    """indigo.device: ping answers `reply` (after `wait`, if given) or raises."""

    def __init__(self, reply=None, error=None, wait=None):
        self.reply, self.error, self.wait = reply, error, wait

    def ping(self, did, suppressLogging=True):
        if self.wait is not None:
            self.wait.wait(2)
        if self.error is not None:
            raise self.error
        return self.reply


@pytest.fixture()
def zw(monkeypatch):
    import indigo
    from mcp_server.tools.extended_tools.extended_tools_handler import ExtendedToolsHandler

    def _make(reply=None, error=None, ping=None):
        z = _ZWave(reply, error)
        monkeypatch.setattr(indigo, "devices",
                            {9: SimpleNamespace(id=9, name="Sensor", address="12")})
        monkeypatch.setattr(indigo, "zwave", z, raising=False)
        monkeypatch.setattr(indigo, "device", ping or _Device(PING_REPLY))
        return ExtendedToolsHandler(None, logger=LOG), z
    return _make


def _errors(caplog):
    return [r for r in caplog.records if r.levelno >= logging.ERROR]


# ── sendConfigParm: Indigo's own keys ────────────────────────────────────────

@pytest.mark.parametrize("reply", [WAITED_ON_ROOT, WAITED_ON_ENDPOINT,
                                   FakeIndigoDict(WAITED_ON_ROOT)],
                         ids=["dict", "endpoint", "indigo.Dict"])
def test_a_waited_config_set_reports_indigos_acknowledgement(zw, reply):
    ext, z = zw(reply=reply)
    out = ext.zwave_send_config_parameter(9, *PARAM, wait_for_ack=True)
    assert z.calls[0][2]["waitUntilAck"] is True
    assert out["success"] is True
    assert out["acknowledged"] is True
    assert out["status"] == "acknowledged"
    assert out["queued_for_next_wake"] is False
    assert "acknowledged by 'Sensor'" in out["message"]
    assert out["detail"]["cmdSuccess"] is True and out["detail"]["nodeId"] == 12


def test_a_refused_waited_config_set_is_a_failure(zw):
    # Not measured: a failed waited send's reply. Taken to be the same keys
    # with cmdSuccess False.
    ext, _ = zw(reply=dict(WAITED_ON_ROOT, cmdSuccess=False))
    out = ext.zwave_send_config_parameter(9, *PARAM, wait_for_ack=True)
    assert out["success"] is False and out["acknowledged"] is False
    assert out["status"] == "not_acknowledged" and "NOT acknowledged" in out["message"]


def test_a_config_set_queued_for_a_sleeping_device_is_queued_not_failed(zw):
    # Unmeasured: Indigo has only been seen to answer queuedForNextWake False.
    # What True means beside either cmdSuccess is a CHOSEN reading of the key's
    # name, pinned here so a change to it is deliberate: queued, not
    # acknowledged, not a failure. Revisit it if a real reply ever carries True.
    for cmd_success in (True, False):
        ext, _ = zw(reply=dict(WAITED_ON_ROOT, cmdSuccess=cmd_success, queuedForNextWake=True))
        out = ext.zwave_send_config_parameter(9, *PARAM, wait_for_ack=True)
        assert out["success"] is True and out["status"] == "queued"
        assert out["queued_for_next_wake"] is True and out["acknowledged"] is None
        assert "queued for the device's next wake" in out["message"]
        assert "not been seen" in out["message"]
        assert out["detail"]["cmdSuccess"] is cmd_success


def test_the_older_success_reply_is_still_read(zw):
    # guard: 3.9.1 read Success too.
    ext, _ = zw(reply={"Success": True, "TimeDelta": 25})
    out = ext.zwave_send_config_parameter(9, *PARAM, wait_for_ack=True)
    assert out["success"] is True and out["acknowledged"] is True


def test_an_unwaited_config_set_answers_none_and_claims_nothing(zw):
    # guard: 3.9.1 claimed nothing either.
    ext, z = zw(reply=None)
    out = ext.zwave_send_config_parameter(9, *PARAM)
    assert z.calls[0][2]["waitUntilAck"] is False
    assert out["success"] is True and out["acknowledged"] is None
    assert "without waiting" in out["message"]


def test_a_waited_config_set_with_no_reply_says_there_was_no_flag(zw):
    # guard: 3.9.1 said the same.
    ext, _ = zw(reply=None)
    out = ext.zwave_send_config_parameter(9, *PARAM, wait_for_ack=True)
    assert out["success"] is True and out["acknowledged"] is None
    assert "no acknowledgement flag" in out["message"]


@pytest.mark.parametrize("reply,wait,status,queued", [
    ({"Success": True, "TimeDelta": 25}, True, "acknowledged", None),
    (None, False, "sent", None),
    (None, True, "no_flag", None),
], ids=["older-success", "unwaited", "waited-none"])
def test_every_config_reply_says_its_status_and_queue(zw, reply, wait, status, queued):
    # The two keys 3.9.2 adds, for the cases the guards above cover.
    ext, _ = zw(reply=reply)
    out = ext.zwave_send_config_parameter(9, *PARAM, wait_for_ack=wait)
    assert out["status"] == status
    assert out["queued_for_next_wake"] is queued


def test_the_zwave_tool_carries_the_acknowledgement_to_the_caller(zw):
    ext, _ = zw(reply=FakeIndigoDict(WAITED_ON_ROOT))
    ctx = SimpleNamespace(logger=LOG, extended_tools_handler=ext)
    out = call_tool(ctx, "zwave", action="set_config_parameter", device_id=9, param_index=3,
                    param_size=1, param_value=5, wait_for_ack=True)
    assert out["success"] is True and out["acknowledged"] is True
    assert out["detail"]["endpoint"] is None


# ── a turned-off interface: a refusal, not an Error ──────────────────────────

def _assert_refusal(out, caplog, sent_nothing):
    assert out["success"] is False
    assert out["refused"] == "interface_not_enabled"
    assert out["interface"] == "Z-Wave"
    assert "Z-Wave is turned off" in out["error"]
    assert ("Nothing was sent" in out["error"]) is sent_nothing
    assert "Interfaces > Z-Wave > Enable" in out["error"]
    assert out["indigo_error"] == f"InterfaceError: {NOT_ENABLED}"
    assert not _errors(caplog), [r.getMessage() for r in _errors(caplog)]
    assert any(r.levelno == logging.WARNING for r in caplog.records)


def test_a_config_set_while_zwave_is_off_is_refused_plainly(zw, caplog):
    ext, z = zw(error=InterfaceError(NOT_ENABLED))
    with caplog.at_level(logging.DEBUG, logger=LOG.name):
        out = ext.zwave_send_config_parameter(9, *PARAM)
    _assert_refusal(out, caplog, sent_nothing=True)
    assert len(z.calls) == 1


@pytest.mark.parametrize("method,args,sent_nothing", [
    ("zwave_stop_network_optimize", (), True),             # measured
    ("zwave_exit_inclusion_exclusion_mode", (), True),     # measured
    ("zwave_start_network_optimize", (None,), False),      # not measured
    ("zwave_start_network_optimize", (9,), False),         # not measured
    ("zwave_enter_inclusion_mode", (), False),             # not measured
    ("zwave_enter_exclusion_mode", (), False),             # not measured
])
def test_every_network_call_while_zwave_is_off_is_refused_plainly(zw, caplog, method, args,
                                                                  sent_nothing):
    # Only the calls measured to send nothing say so; the rest are refused in
    # the same plain words without that claim.
    ext, _ = zw(error=InterfaceError(NOT_ENABLED))
    with caplog.at_level(logging.DEBUG, logger=LOG.name):
        out = getattr(ext, method)(*args)
    _assert_refusal(out, caplog, sent_nothing=sent_nothing)


def test_a_subclass_of_interfaceerror_is_recognised_too(zw, caplog):
    class _Narrower(InterfaceError):
        pass
    ext, _ = zw(error=_Narrower(NOT_ENABLED))
    with caplog.at_level(logging.DEBUG, logger=LOG.name):
        out = ext.zwave_stop_network_optimize()
    assert out["refused"] == "interface_not_enabled" and not _errors(caplog)


def test_any_other_failure_is_still_an_error(zw, caplog):
    # guard
    ext, _ = zw(error=RuntimeError("radio on fire"))
    with caplog.at_level(logging.DEBUG, logger=LOG.name):
        out = ext.zwave_send_config_parameter(9, *PARAM)
    assert out["success"] is False and "refused" not in out
    assert _errors(caplog)


@pytest.mark.parametrize("said", [
    "interface Z-Wave is busy",
    "interface Z-Wave is not enabled for that node",
    "",
], ids=["busy", "longer", "empty"])
def test_an_interfaceerror_for_another_reason_is_still_an_error(zw, caplog, said):
    # guard: only the message measured is a refusal. Anything else Indigo (or
    # anyone) raises as InterfaceError keeps the red Error it had in 3.9.1.
    ext, _ = zw(error=InterfaceError(said))
    with caplog.at_level(logging.DEBUG, logger=LOG.name):
        out = ext.zwave_stop_network_optimize()
    assert out["success"] is False and "refused" not in out
    assert _errors(caplog)


# ── database InterfaceErrors are never Indigo's ──────────────────────────────

class _PgInterfaceError(Exception):
    """A DB-API driver's InterfaceError, as the SQL Logger's PostgreSQL
    driver would raise it (its module path is all that matters here)."""


_PgInterfaceError.__name__ = "InterfaceError"
_PgInterfaceError.__qualname__ = "InterfaceError"
_PgInterfaceError.__module__ = "indigologger.postgresql.exceptions"


DATABASE_ERRORS = pytest.mark.parametrize("error", [
    sqlite3.InterfaceError("bad parameter or other API misuse"),
    sqlite3.InterfaceError(NOT_ENABLED),
    _PgInterfaceError(NOT_ENABLED),
], ids=["sqlite3", "sqlite3-same-words", "postgresql-same-words"])


@DATABASE_ERRORS
def test_a_database_interfaceerror_in_the_history_tools_is_still_an_error(caplog, error):
    # guard: device_history and variable_history send every exception to
    # handle_exception. A database driver's InterfaceError must stay a red
    # Error there, never become "Indigo refused it", even with the same words.
    from mcp_server.tools.base_handler import BaseToolHandler
    handler = BaseToolHandler("plugin_dev_tools", logger=LOG)
    with caplog.at_level(logging.DEBUG, logger=LOG.name):
        out = handler.handle_exception(error, "device_history")
    assert out["success"] is False and "refused" not in out
    assert "Indigo refused" not in out["error"]
    assert _errors(caplog)


@DATABASE_ERRORS
def test_a_database_interfaceerror_is_never_read_as_a_refusal(error):
    # The same, at the reader itself, whichever caller asks.
    from mcp_server.tools.base_handler import interface_refusal
    assert interface_refusal(error) is None
    assert interface_refusal(error, sent_nothing=True) is None


# ── ping: Success and TimeDelta, as Indigo answers ───────────────────────────

@pytest.mark.parametrize("reply", [PING_REPLY, FakeIndigoDict(PING_REPLY)],
                         ids=["dict", "indigo.Dict"])
def test_a_ping_reads_success_and_timedelta(zw, reply):
    # The dict case is a guard. The indigo.Dict case shows the reader now
    # tolerates a reply that offers keys() without iteration; whether Indigo's
    # real ping reply is such an object was not recorded, so this is not proof
    # that 3.9.1 misread a live ping.
    ext, _ = zw(ping=_Device(reply))
    out = ext.ping_device(9)
    assert out["status"] == "answered" and out["reachable"] is True
    assert "(16 ms)" in out["message"]
    assert out["detail"] == PING_REPLY


def test_a_ping_while_zwave_is_off_is_refused_plainly(zw, caplog):
    # A ping while turned off was not measured: refused, without "Nothing was sent".
    ext, _ = zw(ping=_Device(error=InterfaceError(NOT_ENABLED)))
    with caplog.at_level(logging.DEBUG, logger=LOG.name):
        out = ext.ping_device(9)
    _assert_refusal(out, caplog, sent_nothing=False)


def test_a_late_ping_refusal_is_logged_in_plain_words(zw, caplog):
    release = threading.Event()
    ext, _ = zw(ping=_Device(error=InterfaceError(NOT_ENABLED), wait=release))
    ext.PING_WAIT_S = 0.05
    out = ext.ping_device(9)
    assert out["status"] == "pending"
    with caplog.at_level(logging.DEBUG, logger=LOG.name):
        release.set()
        deadline = time.monotonic() + 2
        while "turned off" not in caplog.text and time.monotonic() < deadline:
            time.sleep(0.01)
    assert "Z-Wave is turned off" in caplog.text and not _errors(caplog)
    assert "Nothing was sent" not in caplog.text
