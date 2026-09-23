#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    test_rate_limiter.py
# Description: Behavioural tests for the sliding-window RateLimiter: the
#              per-minute cap, the admin-scope multiplier, per-key isolation,
#              reset_session, and the RateLimitExceeded retry hint.
# Author:      CliveS & Claude Fable 5
# Date:        10-06-2026
# Version:     1.0

import logging

import pytest

from mcp_server.security import RateLimiter, RateLimitExceeded

_LOGGER = logging.getLogger("test-ratelimit")


def _limiter(per_minute=3, admin_multiplier=1.0):
    return RateLimiter(per_minute=per_minute, per_day=5_000,
                       admin_multiplier=admin_multiplier, logger=_LOGGER)


def test_minute_cap_enforced_with_retry_hint():
    rl = _limiter(per_minute=3)
    for _ in range(3):
        rl.check("token-a", {"read"})
    with pytest.raises(RateLimitExceeded) as exc:
        rl.check("token-a", {"read"})
    assert exc.value.window == "per_minute"
    assert exc.value.limit == 3
    assert exc.value.retry_after > 0


def test_admin_scope_gets_multiplied_allowance():
    rl = _limiter(per_minute=2, admin_multiplier=10.0)
    # Non-admin trips after 2…
    rl.check("plain", {"read"})
    rl.check("plain", {"read"})
    with pytest.raises(RateLimitExceeded):
        rl.check("plain", {"read"})
    # …admin sails past 2 (cap is 20).
    for _ in range(10):
        rl.check("boss", {"read", "write", "admin"})


def test_keys_are_isolated():
    rl = _limiter(per_minute=1)
    rl.check("token-a", {"read"})
    rl.check("token-b", {"read"})            # different key, fresh allowance
    with pytest.raises(RateLimitExceeded):
        rl.check("token-a", {"read"})


def test_reset_session_clears_the_bucket():
    rl = _limiter(per_minute=1)
    rl.check("token-a", {"read"})
    with pytest.raises(RateLimitExceeded):
        rl.check("token-a", {"read"})
    rl.reset_session("token-a")
    rl.check("token-a", {"read"})            # allowance restored


_LOG = logging.getLogger("test-v210")


# ── H3: /health must not expose raw bearer tokens ────────────────────────────

def test_rate_limiter_snapshot_masks_bearer_tokens():
    from mcp_server.security import RateLimiter
    rl = RateLimiter(per_minute=100, per_day=5000, logger=_LOG)
    secret = "sk-live-SUPERSECRETTOKEN-abcdef"
    rl.check(secret, {"read"})
    snap = rl.snapshot()
    # The raw token must NOT appear as a key…
    assert secret not in snap
    # …but a stable, non-reversible label must, carrying the counts.
    assert len(snap) == 1
    (masked_key, counts), = snap.items()
    assert masked_key.startswith("token-")
    assert secret[:8] not in masked_key
    assert counts["minute"] == 1


def test_rate_limiter_snapshot_keeps_anonymous_readable():
    from mcp_server.security import RateLimiter
    rl = RateLimiter(per_minute=100, per_day=5000, logger=_LOG)
    rl.check("anonymous", {"read"})
    assert "anonymous" in rl.snapshot()
