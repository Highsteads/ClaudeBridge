#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    secret_redactor.py
# Description: Replace known credential VALUES in a tool's failure output, so a
#              failed execute_indigo_python / run_script can keep its traceback,
#              stdout and stderr instead of losing all of it.
# Author:      CliveS & Claude Opus 5.5
# Date:        23-09-2026
# Version:     1.0

"""
Redact by value, not by field.

Until v2.27.2 a failed ``execute_indigo_python`` or ``run_script`` lost its
whole payload: traceback, stdout and stderr were all replaced by "see the
Claude Bridge event log for details", because any of them COULD carry a
credential. That was safe and it made every failure cost a second call to go
and read the log — 85 failures in ten weeks, each one a round trip.

This module keeps the output and removes the secrets from it. It knows the
secret values from three places:

  1. IndigoSecrets.py — only the settings whose NAME says credential (KEY,
     TOKEN, PASSWORD, PASS, SECRET, PIN, AUTH, CREDENTIAL, SIGN, BEARER,
     PRIVATE). Addresses, usernames and emails are not secrets and redacting
     them would only blind the traceback. The file is PARSED with ``ast``,
     never executed, and re-read whenever it changes on disk, so a rotated
     key is covered without restarting the plugin.
  2. Indigo's own Preferences/secrets.json — the IWS API keys, all of them.
  3. Any extra values the caller supplies (the plugin's credential prefs).

Values shorter than MIN_SECRET_LENGTH are skipped: replacing a four-character
string everywhere would mangle ordinary output and hide nothing worth hiding.

``load()`` raises when a source exists but cannot be read, so the caller can
fall back to the old whole-payload scrub rather than ship an unredacted error.
"""

import ast
import json
import os
import re
import threading
from typing import Any, Callable, Dict, Iterable, Optional, Tuple

MIN_SECRET_LENGTH = 6

_CREDENTIAL_NAME = re.compile(
    r"(KEY|TOKEN|PASSWORD|PASSWD|PASS|SECRET|PIN|AUTH|CREDENTIAL|SIGN|BEARER|PRIVATE)",
    re.IGNORECASE,
)


def is_credential_name(name: str) -> bool:
    """True if a setting's name marks its value as a credential."""
    return bool(_CREDENTIAL_NAME.search(name or ""))


def _leaf_strings(value: Any) -> Iterable[str]:
    """Every string (or int rendered as text) inside a literal value."""
    if isinstance(value, bool):
        return
    if isinstance(value, (str, int)):
        yield str(value)
    elif isinstance(value, dict):
        for v in value.values():
            yield from _leaf_strings(v)
    elif isinstance(value, (list, tuple, set)):
        for v in value:
            yield from _leaf_strings(v)


def credential_values_from_source(source: str) -> Dict[str, str]:
    """Map secret value -> setting name for the credential settings in a
    Python source file. Literal assignments only; a name assigned from an
    earlier name (``UNIFI_PASSWORD = SMLIGHT_PASSWORD``) is followed."""
    tree = ast.parse(source)
    literals: Dict[str, Any] = {}
    found: Dict[str, str] = {}
    for node in tree.body:
        if isinstance(node, ast.Assign):
            targets, value_node = node.targets, node.value
        elif isinstance(node, ast.AnnAssign) and node.value is not None:
            targets, value_node = [node.target], node.value
        else:
            continue
        if isinstance(value_node, ast.Name) and value_node.id in literals:
            value = literals[value_node.id]
        else:
            try:
                value = ast.literal_eval(value_node)
            except (ValueError, TypeError, SyntaxError, MemoryError, RecursionError):
                continue
        for target in targets:
            if not isinstance(target, ast.Name):
                continue
            literals[target.id] = value
            if not is_credential_name(target.id):
                continue
            for text in _leaf_strings(value):
                if len(text) >= MIN_SECRET_LENGTH:
                    found[text] = target.id
    return found


def _iws_values(text: str) -> Dict[str, str]:
    data = json.loads(text)
    found: Dict[str, str] = {}
    for text_value in _leaf_strings(data):
        if len(text_value) >= MIN_SECRET_LENGTH:
            found[text_value] = "IWS_API_KEY"
    return found


class SecretRedactor:
    """Knows the secret values and replaces them in text or JSON payloads."""

    def __init__(
        self,
        secrets_py_path: Optional[str] = None,
        iws_secrets_path: Optional[str] = None,
        extra_values: Optional[Callable[[], Dict[str, str]]] = None,
    ):
        """
        Args:
            secrets_py_path:  IndigoSecrets.py. Absent file = no values from it.
            iws_secrets_path: Indigo's Preferences/secrets.json. Absent = none.
            extra_values:     Callable returning {setting name: value}; only
                              credential-named settings are used.
        """
        self._secrets_py_path  = secrets_py_path
        self._iws_secrets_path = iws_secrets_path
        self._extra_values     = extra_values
        self._lock             = threading.Lock()
        self._cache: Dict[str, Tuple[Tuple[float, int], Dict[str, str]]] = {}

    def _read_file(self, key: str, path: Optional[str],
                   parse: Callable[[str], Dict[str, str]]) -> Dict[str, str]:
        if not path or not os.path.exists(path):
            return {}
        st = os.stat(path)
        stamp = (st.st_mtime, st.st_size)
        cached = self._cache.get(key)
        if cached and cached[0] == stamp:
            return cached[1]
        with open(path, encoding="utf-8") as fh:
            values = parse(fh.read())
        self._cache[key] = (stamp, values)
        return values

    def load(self) -> Dict[str, str]:
        """Return {secret value: label}. Raises if a source that exists
        cannot be read — the caller must then fail closed."""
        with self._lock:
            values: Dict[str, str] = {}
            values.update(self._read_file(
                "secrets_py", self._secrets_py_path, credential_values_from_source))
            values.update(self._read_file(
                "iws", self._iws_secrets_path, _iws_values))
            if self._extra_values is not None:
                for name, value in (self._extra_values() or {}).items():
                    if not is_credential_name(name):
                        continue
                    for text in _leaf_strings(value):
                        if len(text) >= MIN_SECRET_LENGTH:
                            values[text] = name
            return values

    @staticmethod
    def redact_text(text: str, values: Dict[str, str]) -> str:
        """Replace every known value, longest first so a secret that contains
        another is removed whole."""
        if not text or not values:
            return text
        for secret in sorted(values, key=len, reverse=True):
            if secret in text:
                text = text.replace(secret, f"[redacted {values[secret]}]")
        return text

    @classmethod
    def redact_obj(cls, obj: Any, values: Dict[str, str]) -> Any:
        """Redact every string inside a JSON-shaped object, keys included."""
        if isinstance(obj, str):
            return cls.redact_text(obj, values)
        if isinstance(obj, dict):
            return {cls.redact_text(str(k), values): cls.redact_obj(v, values)
                    for k, v in obj.items()}
        if isinstance(obj, list):
            return [cls.redact_obj(v, values) for v in obj]
        return obj
