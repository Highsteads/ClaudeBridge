#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    webhook_pushover_relay.py
# Description: A standalone receiver for ClaudeBridge Event Webhooks that verifies
#              the HMAC signature and relays the event to Pushover via Pushover's
#              own HTTP API — an INDEPENDENT alert path that keeps working even if
#              Indigo's in-house trigger/notification machinery is wedged. Built
#              for a leak-sensor subscription, but works for any subscription.
# Author:      CliveS & Claude Opus 4.8
# Date:        09-06-2026
# Version:     1.0
#
# Usage:
#   python3 webhook_pushover_relay.py --port 9001 --signing-key <KEY>
#
# Credentials are read from IndigoSecrets.py (the estate convention):
#   PUSHOVER_USER_TOKEN  — your Pushover user key (already present)
#   PUSHOVER_APP_TOKEN   — a Pushover application/API token (create one at
#                          https://pushover.net/apps/build — takes a minute)
# If PUSHOVER_APP_TOKEN is absent the relay still runs and LOGS every verified
# event, but cannot send to Pushover until the app token is set.
#
# Each delivery is HMAC-verified with the subscription's signing key (shown once
# by webhook_create), so a forged POST is rejected. Runs over plain HTTP for a
# LAN/loopback receiver — keep it on the box / behind the LAN, and rely on the
# HMAC (not the transport) for authenticity.

import argparse
import hashlib
import hmac
import json
import sys
import time
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

MAX_SKEW_SECONDS = 300
_PUSHOVER_API = "https://api.pushover.net/1/messages.json"

# Read credentials from IndigoSecrets.py (per-key, never fatal if missing).
sys.path.insert(0, "/Library/Application Support/Perceptive Automation")
try:
    from IndigoSecrets import PUSHOVER_USER_TOKEN
except ImportError:
    PUSHOVER_USER_TOKEN = ""
try:
    from IndigoSecrets import PUSHOVER_APP_TOKEN
except ImportError:
    PUSHOVER_APP_TOKEN = ""


def send_pushover(title: str, message: str, priority: int = 0) -> str:
    """Send via Pushover's HTTP API. Returns '' on success or a reason string."""
    if not (PUSHOVER_USER_TOKEN and PUSHOVER_APP_TOKEN):
        return "pushover disabled (set PUSHOVER_APP_TOKEN in IndigoSecrets.py)"
    data = urllib.parse.urlencode({
        "token": PUSHOVER_APP_TOKEN,
        "user": PUSHOVER_USER_TOKEN,
        "title": title[:250],
        "message": message[:1024],
        "priority": str(priority),
    }).encode("utf-8")
    try:
        req = urllib.request.Request(_PUSHOVER_API, data=data, method="POST")
        with urllib.request.urlopen(req, timeout=10) as resp:
            return "" if resp.getcode() == 200 else f"pushover HTTP {resp.getcode()}"
    except Exception as e:
        return f"pushover error: {e}"


def make_handler(signing_keys):
    """signing_keys: list of bytes — a delivery is accepted if it verifies under
    ANY of them (one relay can serve several subscriptions)."""
    seen = set()

    class Relay(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_POST(self):
            body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
            ok, reason = self._verify(self.headers.get("X-ClaudeBridge-Timestamp", ""),
                                      self.headers.get("X-ClaudeBridge-Signature", ""), body)
            if not ok:
                print(f"[REJECTED] {reason}")
                self.send_response(401); self.end_headers(); self.wfile.write(b"rejected")
                return

            try:
                event = json.loads(body)
            except ValueError:
                event = {}
            eid = event.get("event_id")
            if eid and eid in seen:
                self.send_response(200); self.end_headers(); self.wfile.write(b"dup")
                return
            if eid:
                if len(seen) > 10000:
                    seen.clear()
                seen.add(eid)

            human = event.get("human", {})
            title = human.get("title") or event.get("event_type", "Indigo event")
            summary = human.get("summary") or json.dumps(event.get("state", {}))
            # Leak/security events get high priority so they break through quiet hours.
            priority = 1 if "leak" in (title + summary).lower() else 0
            pr = send_pushover(f"Indigo: {title}", summary, priority)
            stamp = time.strftime("%H:%M:%S")
            print(f"[{stamp}] {title} | {summary} | pushover={'sent' if not pr else pr}")

            self.send_response(200); self.end_headers(); self.wfile.write(b"ok")

        def _verify(self, ts, sig, body):
            if not ts or not sig:
                return False, "missing signature headers"
            try:
                if abs(time.time() - int(ts)) > MAX_SKEW_SECONDS:
                    return False, "stale timestamp"
            except ValueError:
                return False, "bad timestamp"
            for key in signing_keys:
                expected = "sha256=" + hmac.new(key, ts.encode() + b"." + body,
                                                hashlib.sha256).hexdigest()
                if hmac.compare_digest(sig, expected):
                    return True, ""
            return False, "HMAC mismatch (no configured key matched)"

    return Relay


def main():
    ap = argparse.ArgumentParser(description="ClaudeBridge webhook -> Pushover relay")
    ap.add_argument("--port", type=int, default=9001)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--signing-key", action="append", default=[], dest="signing_keys",
                    help="subscription signing key; repeat for multiple subscriptions")
    ap.add_argument("--keys-file", help="file with one signing key per line (keeps keys off the cmdline)")
    args = ap.parse_args()
    keys = [k.encode() for k in args.signing_keys]
    if args.keys_file:
        with open(args.keys_file, encoding="utf-8") as f:
            keys += [ln.strip().encode() for ln in f if ln.strip()]
    if not keys:
        sys.exit("no signing keys supplied (use --signing-key or --keys-file)")
    srv = ThreadingHTTPServer((args.host, args.port), make_handler(keys))
    pushover_state = "ENABLED" if (PUSHOVER_USER_TOKEN and PUSHOVER_APP_TOKEN) else "log-only (no PUSHOVER_APP_TOKEN)"
    print(f"Webhook->Pushover relay on http://{args.host}:{args.port}/  | Pushover: {pushover_state}")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        srv.shutdown()


if __name__ == "__main__":
    main()
