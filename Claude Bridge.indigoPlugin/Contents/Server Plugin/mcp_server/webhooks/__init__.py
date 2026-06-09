"""
Outbound webhook subsystem for ClaudeBridge — the "home calls out" push channel.

Distinct from mcp_server/tools/events/ (the in-session poll ring-buffer). This
package watches device/variable changes and POSTs signed events to operator-
approved URLs, behind a default-deny egress firewall (mcp_server/security/
egress_guard.py). Concept inspired by mlamoure's indigo-mcp-server; implemented
independently (that project ships no licence).
"""

from .event_model import Event, new_event_id, SCHEMA_VERSION
from .subscription_model import Subscription
from .subscription_store import SubscriptionStore
from .dwell_timer import DwellTimerQueue
from .webhook_dispatcher import WebhookDispatcher
from .subscription_manager import SubscriptionManager

__all__ = [
    "Event",
    "new_event_id",
    "SCHEMA_VERSION",
    "Subscription",
    "SubscriptionStore",
    "DwellTimerQueue",
    "WebhookDispatcher",
    "SubscriptionManager",
]
