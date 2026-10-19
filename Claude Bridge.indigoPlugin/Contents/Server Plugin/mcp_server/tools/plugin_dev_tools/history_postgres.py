#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    history_postgres.py
# Description: Read the SQL Logger's history from PostgreSQL, for device_history
#              and variable_history. Credentials come from the SQL Logger's own
#              settings first, then from Claude Bridge's own (IndigoSecrets.py,
#              then the plugin's Configure dialog). The connection uses the
#              PostgreSQL driver the SQL Logger bundles, so it adds no package
#              and speaks to the server exactly as the logger does.
#              Everything here returns plain data with times as naive UTC; the
#              handler turns it into the same replies the SQLite path gives.
# Author:      CliveS & Claude Sonnet 5.5
# Date:        19-10-2026
# Version:     1.0
#
# Times. The logger declares ts as `TIMESTAMP DEFAULT CURRENT_TIMESTAMP`. In
# SQLite that default is UTC; in PostgreSQL it is the connection's time zone,
# with no zone stored. So every ts is converted here, in SQL, from the
# session's time zone to UTC, and the handler converts that to local as it does
# for SQLite. Nothing here assumes the server runs in any particular zone.

import os
import sys
import xml.etree.ElementTree as ET
from datetime import datetime
from decimal import Decimal
from typing import Any, Callable, Dict, List, Optional, Tuple

# Folders searched for the SQL Logger bundle, under the Indigo install folder.
_PLUGIN_FOLDERS = ("Plugins", "Plugins (Disabled)")
_SQL_LOGGER_BUNDLE = "SQL Logger.indigoPlugin"

# Keys of the SQL Logger's own settings, and the values it uses when a key was
# never saved (its plugin.py defaults).
_LOGGER_KEYS = {"postgresqlHost": "127.0.0.1", "postgresqlUser": "postgres",
                "postgresqlPassword": "", "postgresqlDatabase": "indigo_history"}

# Claude Bridge's own fallback: IndigoSecrets.py names, and the Configure fields.
SECRET_NAMES = {"host": "CLAUDEBRIDGE_PG_HOST", "database": "CLAUDEBRIDGE_PG_DATABASE",
                "user": "CLAUDEBRIDGE_PG_USER", "password": "CLAUDEBRIDGE_PG_PASSWORD"}
PREF_NAMES = {"host": "history_pg_host", "database": "history_pg_database",
              "user": "history_pg_user", "password": "history_pg_password"}

CONNECT_TIMEOUT = 5          # seconds; the web server waits for this call
QUERY_TIMEOUT_MS = 15_000    # no single statement may hold the dispatch thread longer

# The session time zone, as SQL: turns the logger's naive ts into naive UTC.
_TZ = "current_setting('TimeZone')"


def _to_utc(expr: str) -> str:
    return f"(({expr}) AT TIME ZONE {_TZ}) AT TIME ZONE 'UTC'"


class HistoryDbUnavailable(Exception):
    """The PostgreSQL history cannot be reached. The message is safe to show."""


class BudgetExceeded(Exception):
    """A summary ran past its time budget and was cancelled by the server."""


def _qi(name: str) -> str:
    return '"' + str(name).replace('"', '""') + '"'


# ── Credentials ─────────────────────────────────────────────────────────────

def split_host(raw: str) -> Tuple[str, int]:
    """'host' or 'host:port' as the SQL Logger reads it; the port defaults to 5432."""
    parts = str(raw or "").strip().split(":")
    host = parts[0].strip()
    try:
        port = int(parts[1].strip()) if len(parts) > 1 else 5432
    except ValueError:
        port = 5432
    return host, port


def _settings(host, database, user, password) -> Optional[Dict[str, Any]]:
    # A setting that is not text (a stub, a stray number) is not a setting.
    if not all(isinstance(v, str) for v in (host, database, user)):
        return None
    host, port = split_host(host)
    database = str(database or "").strip()
    user = str(user or "").strip()
    if not host or not database or not user:
        return None
    return {"host": host, "port": port, "database": database, "user": user,
            "password": "" if password is None else str(password)}


def logger_settings(prefs_path: str) -> Optional[Dict[str, Any]]:
    """The SQL Logger's own PostgreSQL settings, or None when its preferences
    cannot be read or leave out the host, database or user. Only the four
    PostgreSQL keys are taken from the file."""
    try:
        root = ET.parse(prefs_path).getroot()
    except Exception:
        return None
    found: Dict[str, str] = {}
    for el in root.iter():
        if el.tag in _LOGGER_KEYS:
            found[el.tag] = (el.text or "")
    merged = {k: found.get(k, default) for k, default in _LOGGER_KEYS.items()}
    return _settings(merged["postgresqlHost"], merged["postgresqlDatabase"],
                     merged["postgresqlUser"], merged["postgresqlPassword"])


def read_secrets(path: str) -> Dict[str, Any]:
    """IndigoSecrets.py read fresh from disk. A running host caches the module
    it imported at start, so a changed key would otherwise go unseen."""
    try:
        with open(path, encoding="utf-8") as fh:
            namespace: Dict[str, Any] = {}
            exec(compile(fh.read(), path, "exec"), namespace)
        return namespace
    except Exception:
        return {}


def claude_bridge_settings(secrets: Dict[str, Any], prefs: Any) -> List[Tuple[str, Dict[str, Any]]]:
    """Claude Bridge's own settings: IndigoSecrets.py first, then the Configure
    dialog, as every Claude Bridge credential is resolved."""
    out = []
    got = _settings(secrets.get(SECRET_NAMES["host"]), secrets.get(SECRET_NAMES["database"]),
                    secrets.get(SECRET_NAMES["user"]), secrets.get(SECRET_NAMES["password"]))
    if got:
        out.append(("Claude Bridge (IndigoSecrets.py)", got))
    try:
        values = {k: prefs.get(v) for k, v in PREF_NAMES.items()} if prefs is not None else {}
    except Exception:
        values = {}
    got = _settings(values.get("host"), values.get("database"),
                    values.get("user"), values.get("password"))
    if got:
        out.append(("Claude Bridge (Configure)", got))
    return out


# ── Driver ──────────────────────────────────────────────────────────────────

def load_driver(indigo_base: str) -> Callable[..., Any]:
    """The SQL Logger's bundled PostgreSQL `open`. Its code is imported from
    the installed bundle, so Claude Bridge ships no database package of its own."""
    for folder in _PLUGIN_FOLDERS:
        server_plugin = os.path.join(indigo_base, folder, _SQL_LOGGER_BUNDLE,
                                     "Contents", "Server Plugin")
        if os.path.isdir(os.path.join(server_plugin, "indigologger")):
            if server_plugin not in sys.path:
                sys.path.append(server_plugin)
            try:
                from indigologger.postgresql import open as pg_open   # type: ignore
            except Exception as exc:
                raise HistoryDbUnavailable(
                    f"The SQL Logger's PostgreSQL driver would not load ({type(exc).__name__}).")
            return pg_open
    raise HistoryDbUnavailable(
        "The SQL Logger plugin is not installed, and its bundled PostgreSQL driver is what "
        "Claude Bridge uses to read the history.")


def _scrub(text: str, secret: str) -> str:
    return text.replace(secret, "***") if secret else text


# ── The reader ──────────────────────────────────────────────────────────────

def _plain(value: Any) -> Any:
    """A value the reply can carry as JSON."""
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, datetime):
        return value.isoformat(sep=" ")
    if isinstance(value, (bytes, bytearray, memoryview)):
        return bytes(value).hex()
    return value


class PostgresHistory:
    """One read-only connection to the PostgreSQL history database."""

    def __init__(self, conn: Any, source: str):
        self._conn = conn
        self.source = source

    # -- connecting --------------------------------------------------------

    @classmethod
    def connect(cls, candidates: List[Tuple[str, Dict[str, Any]]], indigo_base: str,
                opener: Optional[Callable[..., Any]] = None) -> "PostgresHistory":
        """Try each candidate in order and keep the first that connects."""
        if not candidates:
            raise HistoryDbUnavailable(
                "The SQL Logger is set to PostgreSQL, but no PostgreSQL settings could be "
                "read. Fill in the History database fields in Claude Bridge's Configure "
                "dialog, or the CLAUDEBRIDGE_PG_ keys in IndigoSecrets.py.")
        pg_open = opener or load_driver(indigo_base)
        failures = []
        for label, s in candidates:
            try:
                conn = pg_open(host=s["host"], port=s["port"], user=s["user"],
                               password=s["password"], database=s["database"],
                               connect_timeout=CONNECT_TIMEOUT)
            except Exception as exc:
                reason = _scrub(f"{type(exc).__name__}: {str(exc).splitlines()[0] if str(exc) else ''}",
                                s["password"])
                failures.append(f"{label}: {reason}")
                continue
            try:
                conn.execute("SET default_transaction_read_only = on")
                conn.execute(f"SET statement_timeout = {QUERY_TIMEOUT_MS}")
            except Exception:
                try:
                    conn.close()
                except Exception:
                    pass
                raise
            return cls(conn, label)
        raise HistoryDbUnavailable(
            "Could not connect to the PostgreSQL history database. " + "; ".join(failures))

    def close(self) -> None:
        try:
            self._conn.close()
        except Exception:
            pass

    # -- helpers -----------------------------------------------------------

    def _run(self, sql: str, *params: Any) -> List[Any]:
        return list(self._conn.prepare(sql)(*params))

    def has_table(self, table: str) -> bool:
        return bool(self._run(
            "SELECT 1 FROM information_schema.tables WHERE table_name = $1 "
            "AND table_schema = ANY (current_schemas(false))", table))

    def columns(self, table: str) -> List[Tuple[str, str]]:
        """(name, type) of each column, in table order."""
        rows = self._run(
            "SELECT column_name, data_type FROM information_schema.columns "
            "WHERE table_name = $1 AND table_schema = ANY (current_schemas(false)) "
            "ORDER BY ordinal_position", table)
        return [(str(r[0]), str(r[1]).lower()) for r in rows]

    def cutoff(self, hours: int) -> datetime:
        """The start of the window, in the table's own (session-zone) clock."""
        return self._run("SELECT (now() - make_interval(hours => $1))::timestamp",
                         int(hours))[0][0]

    # -- rows --------------------------------------------------------------

    def floor_id(self, table: str, hours: int) -> int:
        """Smallest id whose ts is inside the window, by binary search on the
        primary key (the same reason as for SQLite: ts has no index)."""
        q = _qi(table)
        cutoff = self.cutoff(hours)
        row = self._run(f"SELECT (SELECT min(id) FROM {q}), (SELECT max(id) FROM {q})")[0]
        if row[0] is None:
            return 0
        lo, hi = int(row[0]), int(row[1])
        first = self._run(f"SELECT ts FROM {q} WHERE id = $1", lo)
        if first and first[0][0] is not None and first[0][0] >= cutoff:
            return lo
        newest = self._run(f"SELECT ts FROM {q} WHERE id = $1", hi)
        if not newest or newest[0][0] is None or newest[0][0] < cutoff:
            return hi + 1
        while lo + 1 < hi:
            mid = (lo + hi) // 2
            probe = self._run(f"SELECT id, ts FROM {q} WHERE id <= $1 ORDER BY id DESC LIMIT 1", mid)
            if probe and probe[0][1] is not None and probe[0][1] >= cutoff:
                hi = int(probe[0][0])
            else:
                lo = mid
        return hi

    def _select_list(self, names: List[str]) -> str:
        return ", ".join(f"{_to_utc('ts')} AS ts" if c == "ts" else _qi(c) for c in names)

    def rows(self, table: str, names: List[str], floor_id: int, limit: int) -> List[Tuple[Any, ...]]:
        """Newest-first rows; ts is naive UTC, other values are JSON-safe."""
        got = self._run(f"SELECT {self._select_list(names)} FROM {_qi(table)} "
                        f"WHERE id >= $1 ORDER BY id DESC LIMIT $2", int(floor_id), int(limit))
        return [tuple(v if (n == "ts" and isinstance(v, datetime)) else _plain(v)
                      for n, v in zip(names, r)) for r in got]

    def summary(self, table: str, states: List[Tuple[str, str]], floor_id: int,
                row_cap: int, budget_seconds: float) -> Dict[str, Any]:
        """Counts instead of rows, over an id range only. `states` is
        (name, type) for each state column. Raises BudgetExceeded."""
        q = _qi(table)
        newest = self._run(f"SELECT max(id) FROM {q}")[0][0]
        if newest is None:
            newest = floor_id
        low_id = max(floor_id, int(newest) - row_cap + 1)
        parts = ["count(*)", _to_utc("min(ts)"), _to_utc("max(ts)")]
        for name, kind in states:
            col = _qi(name)
            value = f"{col}::int" if kind == "boolean" else col
            parts += [f"count({col})", f"min({value})", f"max({value})"]
        try:
            self._conn.execute(f"SET statement_timeout = {max(1, int(budget_seconds * 1000))}")
            agg = self._run(f"SELECT {', '.join(parts)} FROM {q} WHERE id >= $1", low_id)
            hour_start = "date_trunc('hour', ts)"
            per_hour = self._run(
                f"SELECT {_to_utc(hour_start)} AS h, count(*) FROM {q} "
                f"WHERE id >= $1 GROUP BY 1", low_id)
        except Exception as exc:
            if getattr(exc, "code", None) == "57014" or "statement timeout" in str(exc).lower():
                raise BudgetExceeded() from exc
            raise
        finally:
            try:
                self._conn.execute(f"SET statement_timeout = {QUERY_TIMEOUT_MS}")
            except Exception:
                pass
        return {"truncated": low_id > floor_id,
                "agg": tuple(_plain(v) if not isinstance(v, datetime) else v for v in (agg[0] if agg else ())),
                "per_hour": [(h, int(n)) for h, n in per_hour]}

    # -- variables ---------------------------------------------------------

    def variable_before(self, table: str, floor_id: int) -> Optional[Tuple[Any, Any]]:
        """(ts as naive UTC, value) of the newest row before the window."""
        got = self._run(f"SELECT {_to_utc('ts')}, value FROM {_qi(table)} "
                        f"WHERE id < $1 ORDER BY id DESC LIMIT 1", int(floor_id))
        return (got[0][0], _plain(got[0][1])) if got else None

    def variable_rows(self, table: str, floor_id: int, limit: int,
                      newest_first: bool) -> List[Tuple[Any, Any]]:
        order = "DESC" if newest_first else "ASC"
        got = self._run(f"SELECT {_to_utc('ts')}, value FROM {_qi(table)} "
                        f"WHERE id >= $1 ORDER BY id {order} LIMIT $2", int(floor_id), int(limit))
        return [(r[0], _plain(r[1])) for r in got]
