#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    webhooks.py
# Description: Outbound webhook subscriptions (ADMIN; ship dark). The handler
#              belongs to the plugin, so it is reached lazily through ctx.plugin.
# Author:      CliveS & Claude Opus 5.5
# Date:        23-09-2026
# Version:     1.0

from ..registry import tool
from ._schema import boolean, enum, id_or_name, number, refuse, string


def _webhooks(ctx, method: str, **kwargs):
    handler = getattr(ctx.plugin, "webhook_handler", None) if ctx.plugin else None
    if handler is None:
        return refuse("webhook subsystem not initialised")
    return getattr(handler, method)(**kwargs)


@tool("webhook_create", scope="admin", sensitive=True,
      description=("Register an OUTBOUND webhook: the home POSTs a signed JSON event to an "
                   "APPROVED external URL when a device/variable condition is met. ADMIN. The "
                   "target must be on the egress allow-list (default-deny — private/LAN ranges "
                   "need an explicit CIDR opt-in). Returns a one-time HMAC signing key — capture "
                   "it. Requires 'Enable Event Webhooks' in the plugin config."),
      properties={
          "webhook_url": string("https URL to POST events to (must be allow-listed)"),
          "entity_type": enum(["device", "variable"], "What to watch"),
          "conditions": {"type": "object",
                         "description": ("Match using bare Indigo state names, e.g. "
                                         "{\"onState\": true}, {\"battery\": {\"lt\": 20}}, or "
                                         "{\"any_change\": true}. Fires on transition INTO "
                                         "match.")},
          "entity_id": id_or_name("Optional specific device/variable id; omit to watch all of "
                                  "the type"),
          "auth_token": string("Optional extra bearer token sent to the receiver"),
          "verify_ssl": boolean("Verify the receiver's TLS cert (default true)"),
          "duration_seconds": number("Optional dwell: condition must hold this long before "
                                     "firing"),
          "max_fires": number("Optional auto-delete after this many deliveries"),
          "max_body_bytes": number("Optional per-event body cap (default 65536, max 1048576)"),
          "description": string("Optional human label"),
      },
      required=["webhook_url", "entity_type", "conditions"])
def webhook_create(ctx, **kwargs):
    return _webhooks(ctx, "create_subscription", **kwargs)


@tool("webhook_list", scope="admin", sensitive=True,
      description=("List outbound webhook subscriptions with delivery-health stats. ADMIN. "
                   "Secrets are redacted (signing key omitted, bearer token shown as ***)."),
      properties={"subscription_id": string("Optional: return just this one")})
def webhook_list(ctx, subscription_id=None):
    return _webhooks(ctx, "list_subscriptions", subscription_id=subscription_id)


@tool("webhook_delete", scope="admin", sensitive=True,
      description="Delete an outbound webhook subscription by id. ADMIN.",
      properties={"subscription_id": string("The subscription id to remove")},
      required=["subscription_id"])
def webhook_delete(ctx, subscription_id):
    return _webhooks(ctx, "delete_subscription", subscription_id=subscription_id)
