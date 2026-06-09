"""
Subscription model — what to watch, where to deliver, and delivery health.

A Subscription pairs a match condition (entity + StateFilter conditions) with a
delivery target (an approved webhook URL + signing key + optional bearer token)
and tracks per-subscription delivery statistics. Deliveries are ALWAYS HMAC-signed
with the per-subscription signing key; the bearer token is an optional extra.

Original ClaudeBridge implementation (concept inspired by mlamoure's
indigo-mcp-server, which ships no licence — nothing copied). Pure stdlib.

SECURITY: `to_dict(include_secrets=False)` is the display/list form — it redacts
the bearer token to "***" and OMITS the signing key entirely, so neither can
leak through a tool result or the admin web page. Only the on-disk store calls
`to_dict(include_secrets=True)`, and that file is 0600 + gitignored.
"""

import secrets
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from .event_model import new_event_id

# Body-size guards: refuse to deliver an oversized payload rather than truncate it.
DEFAULT_MAX_BODY_BYTES = 64 * 1024
MAX_MAX_BODY_BYTES = 1024 * 1024
# Consecutive send-time failures before a subscription auto-quarantines itself.
QUARANTINE_AFTER = 5


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _fresh_stats() -> Dict[str, Any]:
    return {
        "fires": 0,
        "successful_fires": 0,   # only successes count toward max_fires
        "last_fired_at": None,
        "last_success_at": None,
        "last_failure_at": None,
        "last_http_status": None,
        "consecutive_failures": 0,
        "errors": 0,
        "last_error": None,
    }


@dataclass
class Subscription:
    """A single watch->deliver rule."""

    webhook_url: str
    entity_type: str                                   # "device" | "variable"
    conditions: Dict[str, Any] = field(default_factory=dict)
    entity_id: Optional[int] = None                    # None = all entities of the type
    auth_token: str = ""                               # optional extra bearer; redacted on display
    verify_ssl: bool = True
    duration_seconds: Optional[int] = None             # dwell: condition must hold this long
    max_fires: Optional[int] = None                    # auto-delete after this many deliveries
    max_body_bytes: int = DEFAULT_MAX_BODY_BYTES
    description: str = ""
    enabled: bool = True                               # auto-quarantine flips this off
    subscription_id: str = field(default_factory=new_event_id)
    # Per-subscription HMAC key — generated once, revealed once at create, then
    # omitted from every display. Never regenerated (would break the receiver).
    signing_key: str = field(default_factory=lambda: secrets.token_urlsafe(32))
    created_at: str = field(default_factory=_now_iso)
    stats: Dict[str, Any] = field(default_factory=_fresh_stats)

    # ------------------------------------------------------------------
    # Serialisation
    # ------------------------------------------------------------------

    def to_dict(self, include_secrets: bool = False) -> Dict[str, Any]:
        """Serialise. With include_secrets=False (default) the bearer token is
        redacted and the signing key omitted — safe for tool output and the web UI."""
        d = {
            "subscription_id": self.subscription_id,
            "webhook_url": self.webhook_url,
            "entity_type": self.entity_type,
            "entity_id": self.entity_id,
            "conditions": self.conditions,
            "verify_ssl": self.verify_ssl,
            "duration_seconds": self.duration_seconds,
            "max_fires": self.max_fires,
            "max_body_bytes": self.max_body_bytes,
            "description": self.description,
            "enabled": self.enabled,
            "created_at": self.created_at,
            "stats": dict(self.stats),
        }
        if include_secrets:
            d["auth_token"] = self.auth_token
            d["signing_key"] = self.signing_key
        else:
            d["auth_token"] = "***" if self.auth_token else ""
        return d

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "Subscription":
        """Rehydrate from a persisted record (include_secrets=True form). Missing
        keys fall back to defaults so older/partial records still load."""
        # Coerce entity_id defensively — a hand-edited store with a string id
        # ("123") would otherwise never match (int != str). Bad value -> None.
        raw_eid = d.get("entity_id")
        try:
            entity_id = int(raw_eid) if raw_eid not in (None, "") else None
        except (TypeError, ValueError):
            entity_id = None
        sub = cls(
            webhook_url=d.get("webhook_url", ""),
            entity_type=d.get("entity_type", ""),
            conditions=d.get("conditions") or {},
            entity_id=entity_id,
            auth_token=d.get("auth_token", ""),
            verify_ssl=bool(d.get("verify_ssl", True)),
            duration_seconds=d.get("duration_seconds"),
            max_fires=d.get("max_fires"),
            max_body_bytes=int(d.get("max_body_bytes", DEFAULT_MAX_BODY_BYTES)),
            description=d.get("description", ""),
            enabled=bool(d.get("enabled", True)),
        )
        if d.get("subscription_id"):
            sub.subscription_id = d["subscription_id"]
        if d.get("signing_key"):
            sub.signing_key = d["signing_key"]
        if d.get("created_at"):
            sub.created_at = d["created_at"]
        if isinstance(d.get("stats"), dict):
            sub.stats.update(d["stats"])
        return sub

    # ------------------------------------------------------------------
    # Delivery-health bookkeeping
    # ------------------------------------------------------------------

    def record_success(self, http_status: int) -> None:
        now = _now_iso()
        self.stats["fires"] += 1
        self.stats["successful_fires"] += 1   # only successes count toward max_fires
        self.stats["last_fired_at"] = now
        self.stats["last_success_at"] = now
        self.stats["last_http_status"] = http_status
        self.stats["consecutive_failures"] = 0

    def record_failure(self, error: str, http_status: Optional[int] = None) -> None:
        now = _now_iso()
        self.stats["fires"] += 1
        self.stats["last_fired_at"] = now
        self.stats["last_failure_at"] = now
        self.stats["errors"] += 1
        self.stats["consecutive_failures"] += 1
        self.stats["last_error"] = error
        if http_status is not None:
            self.stats["last_http_status"] = http_status
        # Auto-quarantine a persistently-failing target so a hostile or dead
        # receiver can't churn the delivery worker indefinitely.
        if self.stats["consecutive_failures"] >= QUARANTINE_AFTER:
            self.enabled = False
