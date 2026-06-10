"""
On-disk persistence for webhook subscriptions.

Subscriptions survive plugin restarts by being saved to a single JSON file,
written atomically (temp file + os.replace) with 0600 permissions because the
file contains delivery secrets (per-subscription signing keys and optional
bearer tokens — they must persist or authenticated receivers couldn't be
re-reached after a restart). The file lives under Indigo's protected
Preferences/Plugins/<bundle>/ directory, NEVER under /public, and is gitignored.

Fail-closed: a missing file loads as empty; a corrupt file is backed up to
<path>.corrupt and loads as empty (a bad file must never block startup, and must
never silently widen anything). Original ClaudeBridge implementation, stdlib only.
"""

import json
import logging
import os
import tempfile
from typing import List, Optional

from .subscription_model import Subscription

SCHEMA_VERSION = 1


class SubscriptionStore:
    """Atomic, 0600 JSON persistence for a list of Subscriptions."""

    def __init__(self, path: str, logger: Optional[logging.Logger] = None):
        self._path = path
        self._logger = logger or logging.getLogger(__name__)

    def load(self) -> List[Subscription]:
        """Return persisted subscriptions, or [] if the file is missing/corrupt."""
        if not os.path.exists(self._path):
            return []
        # Re-assert 0600 — a file restored from a backup (Time Machine, manual
        # copy) keeps the backup's permissions, and this file holds signing keys.
        try:
            os.chmod(self._path, 0o600)
        except OSError as e:
            self._logger.warning(f"Could not re-assert 0600 on {self._path}: {e}")
        try:
            with open(self._path, "r", encoding="utf-8") as f:
                payload = json.load(f)
        except (OSError, ValueError) as e:
            self._logger.error(
                f"Webhook store {self._path} unreadable ({e}); backing up and "
                f"starting with zero subscriptions."
            )
            self._backup_corrupt()
            return []

        if payload.get("version") != SCHEMA_VERSION:
            self._logger.warning(
                f"Webhook store schema {payload.get('version')!r} != {SCHEMA_VERSION}; "
                f"loading best-effort."
            )

        subs: List[Subscription] = []
        for record in payload.get("subscriptions", []):
            try:
                subs.append(Subscription.from_dict(record))
            except Exception as e:
                self._logger.error(f"Skipping unparseable subscription record: {e}")
        return subs

    def save(self, subscriptions: List[Subscription]) -> None:
        """Atomically write the subscriptions (secrets included) with 0600 perms."""
        directory = os.path.dirname(self._path) or "."
        os.makedirs(directory, exist_ok=True)
        payload = {
            "version": SCHEMA_VERSION,
            "subscriptions": [s.to_dict(include_secrets=True) for s in subscriptions],
        }
        fd, tmp = tempfile.mkstemp(prefix=".webhooks-", suffix=".tmp", dir=directory)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(payload, f, indent=2)
            os.chmod(tmp, 0o600)
            os.replace(tmp, self._path)
        except Exception:
            try:
                os.remove(tmp)
            except OSError:
                pass
            raise

    def _backup_corrupt(self) -> None:
        try:
            os.replace(self._path, self._path + ".corrupt")
        except OSError as e:
            self._logger.error(f"Could not back up corrupt webhook store: {e}")
