"""
MCP tool surface for the outbound webhook subsystem — 3 ADMIN tools.

  webhook_create — register a subscription. Validates the URL through the egress
                   firewall AT CREATE TIME and refuses anything not on the
                   allow-list. Returns the per-subscription HMAC signing key ONCE
                   (it is omitted from every later view, so capture it now).
  webhook_list   — list subscriptions with delivery-health stats. Redacts the
                   bearer token and OMITS the signing key.
  webhook_delete — remove a subscription by id.

All three are classified ADMIN in scope_manager.py — registering an egress target
is a data-leaving-the-house operation, strictly more sensitive than a WRITE.

Original ClaudeBridge implementation.
"""

from typing import Any, Callable, Dict, Optional

from ..base_handler import BaseToolHandler
from ...security.egress_guard import EgressDenied, vet_url
from ...webhooks.subscription_model import (
    DEFAULT_MAX_BODY_BYTES,
    MAX_MAX_BODY_BYTES,
    Subscription,
)

_ALLOWED_ENTITY_TYPES = ("device", "variable")


class WebhookHandler(BaseToolHandler):
    """Create/list/delete outbound webhook subscriptions."""

    def __init__(
        self,
        manager: Any,
        allowlist_provider: Callable[[], Any],
        enabled_provider: Optional[Callable[[], bool]] = None,
        logger=None,
    ):
        super().__init__("webhooks", logger)
        self._manager = manager
        self._allowlist = allowlist_provider
        # Feature ships dark — create is refused until the operator enables it.
        # Default the gate CLOSED: a missing enabled_provider must refuse create,
        # never silently re-open the outbound-egress channel.
        self._enabled = enabled_provider or (lambda: False)

    # ------------------------------------------------------------------
    # create
    # ------------------------------------------------------------------

    def create_subscription(
        self,
        webhook_url: str = "",
        entity_type: str = "",
        conditions: Optional[Dict[str, Any]] = None,
        auth_token: str = "",
        verify_ssl: bool = True,
        entity_id: Optional[Any] = None,
        duration_seconds: Optional[Any] = None,
        max_fires: Optional[Any] = None,
        max_body_bytes: Optional[Any] = None,
        description: str = "",
    ) -> Dict[str, Any]:
        try:
            if not self._enabled():
                return {"success": False, "error": "Event Webhooks are disabled. Enable them "
                        "in Plugins -> Claude Bridge -> Configure (and set an egress allow-list)."}
            if not webhook_url or not isinstance(webhook_url, str):
                return {"success": False, "error": "webhook_url is required"}
            if entity_type not in _ALLOWED_ENTITY_TYPES:
                return {"success": False, "error": "entity_type must be 'device' or 'variable'"}
            if not isinstance(conditions, dict) or not conditions:
                return {"success": False, "error": "conditions must be a non-empty object "
                        "(e.g. {\"onState\": true}, {\"battery\": {\"lt\": 20}}, or {\"any_change\": true})"}
            # any_change fires on every change and short-circuits the transition
            # check, so combining it with a state condition would silently ignore
            # that condition. Refuse the ambiguous combination at create time.
            if conditions.get("any_change") and len(conditions) > 1:
                return {"success": False,
                        "error": "any_change cannot be combined with other conditions"}

            # numeric coercions, each guarded (CB config-coercion convention)
            eid = self._opt_int(entity_id, "entity_id")
            if isinstance(eid, dict):
                return eid
            dwell = self._opt_int(duration_seconds, "duration_seconds")
            if isinstance(dwell, dict):
                return dwell
            fires = self._opt_int(max_fires, "max_fires")
            if isinstance(fires, dict):
                return fires
            body_cap = self._opt_int(max_body_bytes, "max_body_bytes")
            if isinstance(body_cap, dict):
                return body_cap

            if dwell is not None and dwell < 1:
                return {"success": False, "error": "duration_seconds must be >= 1"}
            if dwell is not None and conditions.get("any_change"):
                return {"success": False, "error": "duration_seconds cannot be combined with any_change"}
            if fires is not None and fires < 1:
                return {"success": False, "error": "max_fires must be >= 1"}
            if body_cap is None:
                body_cap = DEFAULT_MAX_BODY_BYTES
            body_cap = max(1, min(MAX_MAX_BODY_BYTES, body_cap))

            # ── egress firewall (create-time) ──
            allowlist = self._allowlist()
            if allowlist.is_empty():
                return {"success": False, "error": "the webhook allow-list is empty (default-deny). "
                        "Add an approved host to IndigoSecrets.py WEBHOOK_ALLOWLIST, "
                        "webhook_allowlist.json, or the plugin config before registering a target."}
            try:
                vetted = vet_url(webhook_url, allowlist, resolve=True)
            except EgressDenied as e:
                return {"success": False, "error": f"refused: {e}"}

            sub = Subscription(
                webhook_url=webhook_url,
                entity_type=entity_type,
                conditions=conditions,
                entity_id=eid,
                auth_token=auth_token or "",
                verify_ssl=bool(verify_ssl),
                duration_seconds=dwell,
                max_fires=fires,
                max_body_bytes=body_cap,
                description=description or "",
            )
            self._manager.add(sub)
            self.info_log(f"created {sub.subscription_id} -> {webhook_url}")
            if not bool(verify_ssl):
                self.warning_log(
                    f"subscription {sub.subscription_id} created with verify_ssl=False — "
                    f"the receiver's TLS cert/hostname will NOT be validated; a network "
                    f"MITM between here and the target could read the payload and any bearer token")

            return {
                "success": True,
                "subscription_id": sub.subscription_id,
                # One-time reveal — the receiver verifies HMAC with this; it is
                # never shown again (webhook_list omits it).
                "signing_key": sub.signing_key,
                "signature_scheme": "HMAC-SHA256 over (X-ClaudeBridge-Timestamp + '.' + raw_body), "
                                    "hex, sent as X-ClaudeBridge-Signature: sha256=<hex>",
                "vetted_ips_at_create": [str(ip) for ip in vetted],
                "note": "Store signing_key now — it is shown only once.",
                "subscription": sub.to_dict(include_secrets=False),
            }
        except Exception as e:
            return self.handle_exception(e, "create_subscription")

    # ------------------------------------------------------------------
    # list / delete
    # ------------------------------------------------------------------

    def list_subscriptions(self, subscription_id: Optional[str] = None) -> Dict[str, Any]:
        try:
            if subscription_id:
                sub = self._manager.get(subscription_id)
                if sub is None:
                    return {"success": False, "error": f"no subscription {subscription_id!r}"}
                return {"success": True, "subscription": sub.to_dict(include_secrets=False)}
            subs = self._manager.list_all()
            return {
                "success": True,
                "count": len(subs),
                "subscriptions": [s.to_dict(include_secrets=False) for s in subs],
            }
        except Exception as e:
            return self.handle_exception(e, "list_subscriptions")

    def delete_subscription(self, subscription_id: str = "") -> Dict[str, Any]:
        try:
            if not subscription_id:
                return {"success": False, "error": "subscription_id is required"}
            if self._manager.delete(subscription_id):
                self.info_log(f"deleted {subscription_id}")
                return {"success": True, "deleted": subscription_id}
            return {"success": False, "error": f"no subscription {subscription_id!r}"}
        except Exception as e:
            return self.handle_exception(e, "delete_subscription")

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _opt_int(value: Any, name: str):
        """Coerce an optional int; return None if absent, or an error dict if bad."""
        if value is None or value == "":
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return {"success": False, "error": f"{name} must be an integer"}
