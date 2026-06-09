"""
Event payload model for outbound webhook deliveries.

Defines the Event dataclass — the JSON body POSTed to a subscriber's URL when a
device or variable change matches a subscription — and a sortable unique id
generator used for de-duplication on the receiving side.

Original ClaudeBridge implementation. The outbound-event-subscription concept is
inspired by mlamoure's indigo-mcp-server, but that project ships no licence, so
nothing here is copied from it — this module is written independently.

Pure stdlib, no Indigo import, so it can be unit-tested in isolation.
"""

import os
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Any, Dict

# Bump if the wire payload shape changes incompatibly. Receivers can branch on it.
SCHEMA_VERSION = "1.0"
PLUGIN_ID = "com.clives.indigoplugin.claudebridge"

# Crockford base32 (no I/L/O/U) — case-insensitive, URL-safe, sorts lexically.
_BASE32 = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"


def _b32(value: int, width: int) -> str:
    """Encode a non-negative int as a fixed-width Crockford-base32 string,
    most-significant digit first (so lexical order matches numeric order)."""
    out = []
    for _ in range(width):
        out.append(_BASE32[value & 0x1F])
        value >>= 5
    return "".join(reversed(out))


def new_event_id() -> str:
    """Return a 26-char time-sortable unique id.

    The leading 10 chars encode the millisecond timestamp, so ids generated
    later sort after earlier ones; the trailing 16 chars are random for
    uniqueness within the same millisecond.
    """
    millis = int(time.time() * 1000) & ((1 << 48) - 1)   # 48-bit ms clock
    rand = int.from_bytes(os.urandom(10), "big")          # 80 bits of entropy
    return _b32(millis, 10) + _b32(rand, 16)


def _now_iso() -> str:
    """Current UTC time as an ISO-8601 string."""
    return datetime.now(timezone.utc).isoformat()


@dataclass
class Event:
    """The JSON document delivered to a subscriber.

    Delivery is at-least-once — a flaky receiver may see the same event twice on
    retry — so receivers MUST de-duplicate on `event_id` (and may additionally
    use `dedupe_key`, which is stable for a given entity+state).
    """

    event_type: str                                   # e.g. "device.state_changed"
    entity: Dict[str, Any] = field(default_factory=dict)   # {kind,id,name,device_type}
    state: Dict[str, Any] = field(default_factory=dict)    # {changed,old,new}
    trigger: Dict[str, Any] = field(default_factory=dict)  # {subscription_id,conditions}
    human: Dict[str, str] = field(default_factory=dict)    # {title,summary}
    dedupe_key: str = ""
    event_id: str = field(default_factory=new_event_id)
    schema_version: str = SCHEMA_VERSION
    timestamp: str = field(default_factory=_now_iso)
    source: Dict[str, str] = field(
        default_factory=lambda: {"system": "indigo", "plugin": PLUGIN_ID}
    )

    def to_dict(self) -> Dict[str, Any]:
        """Plain dict ready for json.dumps()."""
        return asdict(self)
