#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    change_log.py
# Description: A permanent record of every change made through Claude Bridge:
#              which key, which tool, the arguments with secrets blanked, what
#              happened, and the Python or script it ran.
# Author:      CliveS & Claude Opus 5.5
# Date:        25-09-2026
# Version:     1.0

"""
The change log (3.4.0).

Every tools/call that needs the write or admin scope is recorded, whether it
worked, failed or was refused, one JSON object per line in a file per month:

    <Indigo>/Preferences/Plugins/com.clives.indigoplugin.claudebridge/
        change-log/changes-2026-09.jsonl

Nothing ever deletes these files. They are made readable by this Mac user only
(0600, folder 0700), because the arguments include the Python Claude ran.

What goes in an entry, and what never does:

  - the key's NAME from scopes.json ("default" without one), never the key;
  - the tool and its arguments. An argument whose name marks a credential
    (pin, password, token, key...) is replaced outright; every other string
    has each known secret value blanked, the same values the error redaction
    uses (IndigoSecrets.py, Indigo's API keys, the plugin's credential prefs);
  - the outcome: ok, failed, refused or running, and for a failure or refusal
    its first 500 characters, redacted the same way;
  - never the tool's reply. A reply can hold anything, and what changed is in
    the arguments.

If the secret values cannot be read, the arguments are withheld from that entry
rather than written unredacted.

Writing happens on a thread of its own. tools/call runs on the web server's
single request thread, and a disk write there makes every page wait for it.
The queue is bounded; a burst beyond it is counted, logged once, and the count
recorded in the next entry, so a gap in the log is never silent.
"""

import json
import os
import queue
import threading
import time
from datetime import datetime
from typing import Any, Callable, Dict, Iterable, List, Optional

from .secret_redactor import SecretRedactor, is_credential_name

FILE_PREFIX = "changes-"
FILE_SUFFIX = ".jsonl"
MAX_STRING_CHARS = 64 * 1024        # a whole script or block of Python fits
MAX_ERROR_CHARS = 500
QUEUE_MAX = 2000
REDACTED_ARG = "[redacted: credential]"

# execute_indigo_python / run_script called with only a job_id collect an
# earlier run's result; they change nothing, and a client may ask many times.
COLLECT_ONLY_ARGS = frozenset({"job_id", "wait_seconds"})
JOB_TOOLS = frozenset({"execute_indigo_python", "run_script"})


def is_change(required_scope: str) -> bool:
    """A call is a change when it needs more than the read scope."""
    return required_scope in ("write", "admin")


def is_collect_only(tool: str, args: Dict[str, Any]) -> bool:
    return tool in JOB_TOOLS and bool(args) and set(args) <= COLLECT_ONLY_ARGS


def _cap(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + f"... [{len(text) - limit} more characters not kept]"


def redact_args(args: Any, values: Dict[str, str], name: str = "") -> Any:
    """Arguments as they are kept: a credential-named argument replaced, every
    other string with known secret values blanked, long strings capped."""
    if name and is_credential_name(name) and args not in (None, "", [], {}):
        return REDACTED_ARG
    if isinstance(args, str):
        return _cap(SecretRedactor.redact_text(args, values), MAX_STRING_CHARS)
    if isinstance(args, dict):
        return {str(k): redact_args(v, values, str(k)) for k, v in args.items()}
    if isinstance(args, (list, tuple)):
        return [redact_args(v, values) for v in args]
    if isinstance(args, (int, float, bool)) or args is None:
        return args
    return _cap(SecretRedactor.redact_text(str(args), values), MAX_STRING_CHARS)


class ChangeLog:
    """Append-only, month-per-file record of changes. record() never blocks
    and never raises; the writer thread does the redaction and the disk."""

    def __init__(self, folder: str, secret_values: Callable[[], Dict[str, str]],
                 logger=None, clock: Callable[[], float] = time.time):
        self.folder = folder
        self._secret_values = secret_values
        self._logger = logger
        self._clock = clock
        self._queue: "queue.Queue[Optional[Dict[str, Any]]]" = queue.Queue(maxsize=QUEUE_MAX)
        self._dropped = 0
        self._drop_warned = False
        self._write_warned = False
        self._lock = threading.Lock()
        self._job_keys: Dict[str, str] = {}          # job_id -> key name, for "job finished"
        # A job that finished before its "running" entry was recorded (the
        # finish listener fires on the job's thread, which can win the race).
        self._early_finish: Dict[str, Dict[str, Any]] = {}
        self._thread = threading.Thread(target=self._run, daemon=True, name="ChangeLogWriter")
        self._thread.start()

    # ── recording (any thread) ─────────────────────────────────────────────
    def record(self, *, key: str, tool: str, args: Optional[Dict[str, Any]],
               outcome: str, duration_ms: Optional[int] = None,
               error: Optional[str] = None, job_id: Optional[str] = None,
               scope: Optional[str] = None) -> None:
        """Queue one entry. The arguments are copied now (the caller's dict
        may change) and redacted on the writer thread."""
        entry: Dict[str, Any] = {
            "ts":      self._clock(),
            "key":     key or "anonymous",
            "tool":    tool,
            "outcome": outcome,
        }
        if scope:
            entry["scope"] = scope
        if args is not None:
            try:
                entry["args"] = json.loads(json.dumps(args, default=str))
            except Exception:
                entry["args"] = {"unreadable": str(type(args).__name__)}
        if duration_ms is not None:
            entry["duration_ms"] = int(duration_ms)
        if error:
            entry["error"] = str(error)
        early = None
        if job_id:
            entry["job_id"] = str(job_id)
            with self._lock:
                early = self._early_finish.pop(str(job_id), None)
                if early is None:
                    self._job_keys[str(job_id)] = entry["key"]
                    _trim(self._job_keys)
        self._put(entry)
        if early is not None:
            early["key"] = entry["key"]
            self._put(early)

    def record_job_finished(self, *, tool: str, job_id: str, ok: bool,
                            error: Optional[str] = None,
                            seconds: Optional[float] = None) -> None:
        """A background run has finished. Recorded only for a run whose call
        came back "running": one that finished inside its call already has its
        outcome in that call's entry. A finish that beats its own "running"
        entry is held until that entry arrives."""
        entry: Dict[str, Any] = {"ts": self._clock(), "key": "", "tool": tool,
                                 "outcome": "ok" if ok else "failed",
                                 "job_id": str(job_id), "event": "job finished"}
        if seconds is not None:
            entry["duration_ms"] = int(seconds * 1000)
        if error:
            entry["error"] = str(error)
        with self._lock:
            key = self._job_keys.pop(str(job_id), None)
            if key is None:
                self._early_finish[str(job_id)] = entry
                _trim(self._early_finish)
                return
        entry["key"] = key
        self._put(entry)

    def _put(self, entry: Dict[str, Any]) -> None:
        try:
            self._queue.put_nowait(entry)
        except queue.Full:
            with self._lock:
                self._dropped += 1
                warn = not self._drop_warned
                self._drop_warned = True
            if warn and self._logger:
                self._logger.warning("Change log: more changes arrived than could be written; "
                                     "the next entry records how many were missed")

    # ── writing (writer thread) ────────────────────────────────────────────
    def _run(self) -> None:
        while True:
            entry = self._queue.get()
            try:
                if entry is None:
                    return
                self._write(self._finish(entry))
                self._write_warned = False
            except Exception as exc:            # noqa: BLE001 — the writer must not die
                if not self._write_warned and self._logger:
                    self._logger.warning(f"Change log: could not write an entry ({exc}); "
                                         f"it will keep trying with the next one")
                self._write_warned = True
            finally:
                self._queue.task_done()

    def _finish(self, entry: Dict[str, Any]) -> Dict[str, Any]:
        """Redact, stamp and cap one entry just before it is written."""
        with self._lock:
            missed, self._dropped = self._dropped, 0
            if missed:
                self._drop_warned = False
        try:
            values = self._secret_values() or {}
            if "args" in entry:
                entry["args"] = redact_args(entry["args"], values)
            if "error" in entry:
                entry["error"] = _cap(SecretRedactor.redact_text(entry["error"], values),
                                      MAX_ERROR_CHARS)
        except Exception as exc:                # noqa: BLE001 — fail closed
            entry.pop("args", None)
            if "error" in entry:
                entry["error"] = "[withheld: the secret values could not be read]"
            entry["args_withheld"] = f"the secret values could not be read ({type(exc).__name__})"
        ts = entry.pop("ts")
        out = {"time": datetime.fromtimestamp(ts).astimezone().isoformat(timespec="seconds")}
        out.update(entry)
        if missed:
            out["missed_before_this"] = missed
        return out

    def _path_for(self, when: datetime) -> str:
        return os.path.join(self.folder, f"{FILE_PREFIX}{when:%Y-%m}{FILE_SUFFIX}")

    def _write(self, out: Dict[str, Any]) -> None:
        os.makedirs(self.folder, mode=0o700, exist_ok=True)
        path = self._path_for(datetime.fromisoformat(out["time"]))
        line = json.dumps(out, ensure_ascii=False, default=str) + "\n"
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
        try:
            os.write(fd, line.encode("utf-8"))
        finally:
            os.close(fd)

    def flush(self, timeout: float = 5.0) -> bool:
        """Wait until everything queued so far is on disk (tests, shutdown).
        False if the writer did not catch up in time."""
        deadline = time.monotonic() + timeout
        while self._queue.unfinished_tasks:
            if time.monotonic() > deadline:
                return False
            time.sleep(0.005)
        return True

    def stop(self, timeout: float = 2.0) -> None:
        """Write what is queued, then stop the writer."""
        try:
            self._queue.put(None, timeout=timeout)
        except queue.Full:
            return
        self._thread.join(timeout)

    # ── reading ────────────────────────────────────────────────────────────
    def files(self) -> List[str]:
        try:
            names = sorted(n for n in os.listdir(self.folder)
                           if n.startswith(FILE_PREFIX) and n.endswith(FILE_SUFFIX))
        except OSError:
            return []
        return [os.path.join(self.folder, n) for n in names]

    def read(self, *, limit: int = 20, since: Optional[str] = None,
             tool: Optional[str] = None, key: Optional[str] = None,
             outcome: Optional[str] = None) -> Dict[str, Any]:
        """Newest first. `since` is a date or date-time in ISO form; the
        filters match exactly, ignoring case. Reads files newest first and
        stops as soon as it has `limit` matches."""
        limit = max(1, min(int(limit), 500))
        since_dt = _parse_since(since)
        want_tool = (tool or "").lower() or None
        want_key = (key or "").lower() or None
        want_outcome = (outcome or "").lower() or None
        found: List[Dict[str, Any]] = []
        skipped = 0
        for path in reversed(self.files()):
            if since_dt is not None and _month_of(path) < (since_dt.year, since_dt.month):
                break
            for entry in reversed(_read_lines(path)):
                if entry is None:
                    skipped += 1
                    continue
                if since_dt is not None and _entry_time(entry) < since_dt:
                    continue
                if want_tool and str(entry.get("tool", "")).lower() != want_tool:
                    continue
                if want_key and str(entry.get("key", "")).lower() != want_key:
                    continue
                if want_outcome and str(entry.get("outcome", "")).lower() != want_outcome:
                    continue
                if len(found) == limit:         # one past the page: there is more
                    return {"entries": found, "more": True, "unreadable_lines": skipped}
                found.append(entry)
        return {"entries": found, "more": False, "unreadable_lines": skipped}


def _trim(d: Dict[str, Any], most: int = 200) -> None:
    """Keep a bookkeeping dict bounded: drop the oldest half past `most`."""
    if len(d) > most:
        for old in list(d)[:most // 2]:
            d.pop(old, None)


def _read_lines(path: str) -> List[Optional[Dict[str, Any]]]:
    out: List[Optional[Dict[str, Any]]] = []
    try:
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                    out.append(obj if isinstance(obj, dict) else None)
                except ValueError:
                    out.append(None)
    except OSError:
        pass
    return out


def _month_of(path: str):
    stem = os.path.basename(path)[len(FILE_PREFIX):-len(FILE_SUFFIX)]
    try:
        y, m = stem.split("-")
        return int(y), int(m)
    except ValueError:
        return (0, 0)


def _parse_since(since: Optional[str]) -> Optional[datetime]:
    if not since:
        return None
    try:
        dt = datetime.fromisoformat(str(since).strip())
    except ValueError:
        raise ValueError(f"since must be a date like 2026-09-25 or 2026-09-25T14:30, got {since!r}")
    return dt.astimezone() if dt.tzinfo is None else dt


def _entry_time(entry: Dict[str, Any]) -> datetime:
    try:
        dt = datetime.fromisoformat(str(entry.get("time")))
        return dt if dt.tzinfo else dt.astimezone()
    except ValueError:
        return datetime.min.replace(tzinfo=datetime.now().astimezone().tzinfo)


def summarise(entries: Iterable[Dict[str, Any]], max_chars: int = 200) -> List[Dict[str, Any]]:
    """Entries with every argument string cut to max_chars, for a short view."""
    def cut(v):
        if isinstance(v, str):
            return v if len(v) <= max_chars else v[:max_chars] + f"... [{len(v) - max_chars} more]"
        if isinstance(v, dict):
            return {k: cut(x) for k, x in v.items()}
        if isinstance(v, list):
            return [cut(x) for x in v]
        return v
    return [cut(dict(e)) for e in entries]


_OUTCOME_WORDS = {"ok": "done", "failed": "failed", "refused": "refused",
                  "running": "started in the background"}


def describe(entry: Dict[str, Any]) -> str:
    """One entry as a line a person can read, for the menu item."""
    try:
        when = datetime.fromisoformat(str(entry.get("time"))).strftime("%d %b %H:%M:%S")
    except ValueError:
        when = str(entry.get("time", "?"))
    args = entry.get("args") if isinstance(entry.get("args"), dict) else {}
    what = str(entry.get("tool", "?"))
    if entry.get("event") == "job finished":
        what += " (background job finished)"
    elif args.get("action"):
        what += f" {args['action']}"
    outcome = str(entry.get("outcome", "?"))
    line = f"{when}  key '{entry.get('key', '?')}'  {what}: {_OUTCOME_WORDS.get(outcome, outcome)}"
    if entry.get("job_id"):
        line += f" (job {entry['job_id']})"
    if entry.get("duration_ms") is not None and outcome != "running":
        line += f" in {entry['duration_ms'] / 1000:.1f} s"
    if entry.get("error"):
        err = str(entry["error"]).replace("\n", " ")
        line += f" - {err[:120]}{'...' if len(err) > 120 else ''}"
    return line
