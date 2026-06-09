#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    webhook_receiver.py
# Description: A tiny, dependency-free reference receiver for ClaudeBridge's
#              outbound Event Webhooks. It listens for the signed POSTs the plugin
#              sends, VERIFIES the HMAC-SHA256 signature against your subscription's
#              signing key, and prints each event. Use it to see the feature working
#              end to end, or as the starting point for your own handler.
# Author:      CliveS & Claude Opus 4.8
# Date:        09-06-2026
# Version:     1.0
#
# Usage:
#   python3 webhook_receiver.py --port 9000 --signing-key <KEY-FROM-webhook_create>
#
# Then register a subscription pointed at this machine, e.g. (via Claude):
#   webhook_create(webhook_url="https://your-host:9000/hook", entity_type="device",
#                  conditions={"onState": true})
# The signing key is shown ONCE in the webhook_create result — paste it above.
#
# This example serves PLAIN HTTP for simplicity. ClaudeBridge sends over https by
# default (and only allows http to hosts on its plain-HTTP allow-list), so for a
# real deployment put this behind a TLS-terminating reverse proxy, or extend it
# with ssl.SSLContext.wrap_socket. Verifying the HMAC is what actually proves the
# request came from your plugin — TLS protects it in transit.

import argparse
import hashlib
import hmac
import json
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

# How old a signed timestamp may be before we reject it (replay protection).
MAX_SKEW_SECONDS = 300


def make_handler(signing_key: bytes):
    class WebhookReceiver(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass  # quiet the default access log

        def do_POST(self):
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length)

            ts = self.headers.get("X-ClaudeBridge-Timestamp", "")
            sig = self.headers.get("X-ClaudeBridge-Signature", "")

            ok, reason = self._verify(ts, sig, body)
            if not ok:
                print(f"[REJECTED] {reason}")
                self.send_response(401)
                self.end_headers()
                self.wfile.write(b"signature rejected")
                return

            try:
                event = json.loads(body)
            except ValueError:
                event = {"_raw": body.decode("utf-8", "replace")}

            human = event.get("human", {})
            print(f"[OK] {event.get('event_type', '?')} | "
                  f"{human.get('summary') or human.get('title') or ''} | "
                  f"event_id={event.get('event_id', '?')}")
            print(json.dumps(event, indent=2))
            print("-" * 60)

            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"ok")

        def _verify(self, ts: str, sig: str, body: bytes):
            if not ts or not sig:
                return False, "missing signature headers"
            try:
                skew = abs(time.time() - int(ts))
            except ValueError:
                return False, "bad timestamp"
            if skew > MAX_SKEW_SECONDS:
                return False, f"stale timestamp (skew {skew:.0f}s)"
            expected = "sha256=" + hmac.new(
                signing_key, ts.encode() + b"." + body, hashlib.sha256
            ).hexdigest()
            # constant-time compare
            if not hmac.compare_digest(sig, expected):
                return False, "HMAC mismatch (wrong signing key?)"
            return True, ""

    return WebhookReceiver


def main():
    ap = argparse.ArgumentParser(description="ClaudeBridge webhook reference receiver")
    ap.add_argument("--port", type=int, default=9000)
    ap.add_argument("--host", default="0.0.0.0")
    ap.add_argument("--signing-key", required=True,
                    help="the signing key shown once by webhook_create")
    args = ap.parse_args()

    handler = make_handler(args.signing_key.encode("utf-8"))
    server = ThreadingHTTPServer((args.host, args.port), handler)
    print(f"Listening for ClaudeBridge webhooks on http://{args.host}:{args.port}/  "
          f"(Ctrl-C to stop)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping.")
        server.shutdown()


if __name__ == "__main__":
    main()
