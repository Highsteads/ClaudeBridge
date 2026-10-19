#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    test_history_source.py
# Description: device_history and variable_history read SQLite or PostgreSQL,
#              whichever the SQL Logger uses. They must never answer a
#              PostgreSQL logger from the old indigo_history.sqlite left behind
#              (it used to say success with no rows), must refuse any other
#              database, say when the SQLite file was last written, and warn
#              when it looks abandoned. The PostgreSQL password sits in the
#              same preferences file and must never reach a reply.
# Author:      CliveS & Claude Sonnet 5.5
# Date:        19-10-2026
# Version:     1.0

import os
import sqlite3
import time

import pytest

PASSWORD = "hunter2-not-a-real-password"


@pytest.fixture()
def env(tmp_path, monkeypatch):
    from mcp_server.tools.plugin_dev_tools import plugin_dev_tools_handler as mod

    db_path = str(tmp_path / "indigo_history.sqlite")
    conn = sqlite3.connect(db_path)
    conn.execute("CREATE TABLE device_history_9 (id INTEGER PRIMARY KEY, ts TIMESTAMP, watts REAL)")
    conn.execute("CREATE TABLE variable_history_5 (id INTEGER PRIMARY KEY, ts TIMESTAMP, value TEXT)")
    conn.commit()
    conn.close()

    prefs_dir = tmp_path / "Preferences" / "Plugins"
    prefs_dir.mkdir(parents=True)
    monkeypatch.setattr(mod, "_indigo_base", lambda: str(tmp_path))
    monkeypatch.setattr(mod, "_sql_logger_db", lambda: db_path)

    def set_type(db_type):
        body = (f'<databaseType type="string">{db_type}</databaseType>'
                f'<postgresqlPassword type="string">{PASSWORD}</postgresqlPassword>')
        (prefs_dir / mod._SQL_LOGGER_PREFS).write_text(f"<plist>{body}</plist>", encoding="utf-8")

    class Env:
        pass

    e = Env()
    e.mod, e.db_path, e.set_type, e.prefs_dir = mod, db_path, set_type, prefs_dir
    e.handler = mod.PluginDevToolsHandler(data_provider=None)
    return e


def _never_open(monkeypatch, mod):
    def boom(*a, **k):
        raise AssertionError("the SQLite file was opened")
    monkeypatch.setattr(mod.sqlite3, "connect", boom)


def test_the_type_is_read_from_the_logger_preferences(env):
    env.set_type("postgresql")
    assert env.mod._sql_logger_type() == "postgresql"
    env.set_type("sqlite")
    assert env.mod._sql_logger_type() == "sqlite"


def test_missing_preferences_are_unknown_not_a_refusal(env):
    assert env.mod._sql_logger_type() is None
    assert env.mod._history_source_refusal(None) is None


@pytest.mark.parametrize("call", [
    lambda h: h.device_history(9),
    lambda h: h.device_history(9, summary=True),
    lambda h: h.variable_history(5),
    lambda h: h.variable_history(5, summary=True),
])
def test_a_database_that_is_neither_sqlite_nor_postgresql_is_refused_unread(env, monkeypatch, call):
    env.set_type("mysql")
    _never_open(monkeypatch, env.mod)
    reply = call(env.handler)
    assert reply["success"] is False
    assert reply["sql_logger_type"] == "mysql"
    assert "rows" not in reply and "row_count" not in reply


def test_the_refusal_never_carries_the_password(env):
    env.set_type("mysql")
    reply = env.handler.device_history(9)
    assert PASSWORD not in repr(reply)


@pytest.mark.parametrize("call", [
    lambda h: h.device_history(9),
    lambda h: h.variable_history(5),
])
def test_postgresql_never_falls_back_to_the_stale_sqlite_file(env, monkeypatch, call):
    """The 3.8.1 fault: a PostgreSQL logger was answered from a leftover file."""
    env.set_type("postgresql")
    _never_open(monkeypatch, env.mod)

    def down():
        raise env.mod._pgh.HistoryDbUnavailable("no PostgreSQL settings")
    monkeypatch.setattr(env.mod, "_pg_connect", down)
    reply = call(env.handler)
    assert reply["success"] is False
    assert reply["sql_logger_type"] == "postgresql"
    assert "rows" not in reply and "row_count" not in reply


def test_sqlite_is_read_as_before_and_reports_when_it_was_written(env):
    env.set_type("sqlite")
    reply = env.handler.device_history(9)
    assert reply["success"] is True and reply["row_count"] == 0
    assert reply["db_last_written"]
    assert "db_stale" not in reply and "warning" not in reply
    reply = env.handler.variable_history(5)
    assert reply["success"] is True
    assert reply["db_last_written"]


def test_an_unreadable_type_still_reads_the_file(env):
    reply = env.handler.device_history(9)
    assert reply["success"] is True


def test_an_abandoned_file_warns_that_empty_is_not_unchanged(env):
    env.set_type("sqlite")
    old = time.time() - 5 * 3600
    os.utime(env.db_path, (old, old))
    for reply in (env.handler.device_history(9), env.handler.variable_history(5)):
        assert reply["success"] is True
        assert reply["db_stale"] is True
        assert "does not mean nothing changed" in reply["warning"]


def test_the_write_ahead_log_counts_as_a_write(env):
    env.set_type("sqlite")
    old = time.time() - 5 * 3600
    os.utime(env.db_path, (old, old))
    with open(env.db_path + "-wal", "wb") as fh:
        fh.write(b"x")
    assert "db_stale" not in env.handler.device_history(9)


def test_an_error_reply_is_left_alone(env):
    env.set_type("sqlite")
    reply = env.handler.device_history(12345)   # no such table
    assert reply["success"] is False
    assert "db_last_written" not in reply
