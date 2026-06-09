"""
Outbound webhook delivery.

`dispatch(sub, event)` is non-blocking — it enqueues and returns immediately so
Indigo's change-callback thread is never held up. A single daemon worker drains
the queue and delivers each event with this discipline:

  * SEND-TIME re-validation — every delivery re-runs the egress firewall
    (vet_url) against a freshly-read allow-list. A target that has rebound to a
    blocked address since registration is dropped, never sent. This is the real
    security boundary (create-time validation is only UX).
  * CONNECTION PINNING — the TCP socket connects to the exact IP vet_url
    returned, while TLS SNI + certificate validation use the original hostname.
    The HTTP client therefore cannot perform its own second DNS resolution to a
    different (malicious) address.
  * NO REDIRECTS — a 3xx is treated as a delivery failure, never followed
    (redirect-to-internal is the classic SSRF bypass).
  * HMAC-SHA256 signing over `timestamp + "." + body`, tight timeouts, a
    concurrency cap, and interruptible backoff so a plugin reload is clean.

Original ClaudeBridge implementation, stdlib only.
"""

import hashlib
import hmac
import http.client
import json
import logging
import queue
import socket
import ssl
import threading
import time
from typing import Any, Callable, Dict, Optional
from urllib.parse import urlsplit

from ..security.egress_guard import EgressDenied, vet_url


class WebhookDispatcher:
    """Async, SSRF-revalidating, IP-pinning webhook delivery."""

    def __init__(
        self,
        allowlist_provider: Callable[[], Any],
        logger: Optional[logging.Logger] = None,
        on_expired: Optional[Callable[[Any], None]] = None,
        persist: Optional[Callable[[], None]] = None,
        max_concurrency: int = 4,
        connect_timeout: int = 5,
        total_timeout: int = 10,
        max_retries: int = 3,
        retry_base_delay: float = 1.0,
        per_minute: int = 60,
        per_day: int = 5000,
        max_queue: int = 10000,
    ):
        self._allowlist_provider = allowlist_provider
        self._logger = logger or logging.getLogger(__name__)
        self._on_expired = on_expired
        self._persist = persist
        self._connect_timeout = connect_timeout
        self._total_timeout = total_timeout
        self._max_retries = max_retries
        self._retry_base = retry_base_delay
        self._per_minute = per_minute
        self._per_day = per_day

        # Bounded queue so a state-change storm with a slow receiver can't grow
        # memory without limit; dispatch() drops (and counts) when full.
        self._queue: "queue.Queue" = queue.Queue(maxsize=max_queue)
        self._dropped = 0
        self._worker: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self._sem = threading.Semaphore(max_concurrency)
        self._recent: list = []          # delivery timestamps, for the rate cap
        self._rate_lock = threading.Lock()

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self) -> None:
        if self._worker and self._worker.is_alive():
            return
        self._stop.clear()
        self._worker = threading.Thread(
            target=self._worker_loop, name="webhook-dispatcher", daemon=True
        )
        self._worker.start()

    def stop(self) -> None:
        self._stop.set()
        try:
            self._queue.put_nowait(None)   # best-effort wake; the worker also polls _stop
        except queue.Full:
            pass
        if self._worker and self._worker.is_alive():
            # Join budget must exceed the worst-case single in-flight delivery
            # (connect + total socket timeout) or the worker can be left orphaned
            # mid-delivery on a plugin reload (the IndigoPluginHost3 orphan gotcha).
            self._worker.join(timeout=self._connect_timeout + self._total_timeout + 2)
            if self._worker.is_alive():
                self._logger.warning("webhook-dispatcher worker still alive after join budget")

    def dispatch(self, sub: Any, event: Any) -> None:
        """Non-blocking enqueue. Safe to call from the Indigo callback thread.
        Drops (and counts) the event if the bounded queue is full rather than
        ever blocking the Indigo callback thread."""
        if self._stop.is_set():
            return
        try:
            self._queue.put_nowait((sub, event))
        except queue.Full:
            self._dropped += 1
            self._logger.warning(
                f"webhook delivery queue full ({self._queue.maxsize}); event dropped "
                f"(total dropped this run: {self._dropped})")

    def get_stats(self) -> Dict[str, Any]:
        return {"queue_depth": self._queue.qsize(), "running": bool(self._worker and self._worker.is_alive())}

    # ------------------------------------------------------------------
    # Worker
    # ------------------------------------------------------------------

    def _worker_loop(self) -> None:
        while not self._stop.is_set():
            try:
                item = self._queue.get(timeout=1.0)
            except queue.Empty:
                continue
            if item is None:
                break
            sub, event = item
            try:
                self._deliver(sub, event)
            except Exception:
                self._logger.exception("Unexpected error delivering webhook (contained)")

    def _rate_ok(self) -> bool:
        now = time.time()
        with self._rate_lock:
            self._recent = [t for t in self._recent if now - t < 86400]
            if len(self._recent) >= self._per_day:
                return False
            if sum(1 for t in self._recent if now - t < 60) >= self._per_minute:
                return False
            self._recent.append(now)
            return True

    def _deliver(self, sub: Any, event: Any) -> None:
        if not sub.enabled:
            return
        # Pre-send drop paths (rate cap, egress deny, body cap) record the failure
        # in memory but do NOT persist — under a storm they would each rewrite the
        # whole store, and the in-memory quarantine still kicks in after 5 fails.
        if not self._rate_ok():
            sub.record_failure("global webhook rate cap reached; delivery dropped")
            self._logger.warning(f"webhook {sub.subscription_id}: rate cap hit, dropped")
            return

        # 1. SEND-TIME firewall re-check (rebinding defence). Drop on any denial.
        try:
            allowlist = self._allowlist_provider()
            vetted = vet_url(sub.webhook_url, allowlist, resolve=True)
        except EgressDenied as e:
            sub.record_failure(f"send-time egress check failed: {e}")
            self._logger.warning(f"webhook {sub.subscription_id} dropped: {e}")
            return

        # 2. body + size cap (measured on encoded bytes; over-cap => fail, never truncate-send)
        body = json.dumps(event.to_dict(), default=str).encode("utf-8")
        if len(body) > sub.max_body_bytes:
            sub.record_failure(f"payload {len(body)}B exceeds cap {sub.max_body_bytes}B")
            return

        # 3. sign
        ts = str(int(time.time()))
        sig = hmac.new(sub.signing_key.encode("utf-8"), (ts + ".").encode("utf-8") + body, hashlib.sha256).hexdigest()
        headers = {
            "Content-Type": "application/json",
            "User-Agent": "ClaudeBridge-Webhook/1.0",
            "X-ClaudeBridge-Timestamp": ts,
            "X-ClaudeBridge-Signature": "sha256=" + sig,
            "X-Event-Id": getattr(event, "event_id", ""),
            "X-Event-Type": getattr(event, "event_type", ""),
            "X-Subscription-Id": sub.subscription_id,
        }
        if sub.auth_token:
            headers["Authorization"] = "Bearer " + sub.auth_token

        # 4. deliver to the PINNED ip, with retry on 5xx / network error
        pinned = str(vetted[0])
        for attempt in range(self._max_retries + 1):
            try:
                status = self._post_pinned(sub.webhook_url, pinned, headers, body, sub.verify_ssl)
            except Exception as e:
                sub.record_failure(f"delivery error: {e}")
                self._save()
                if attempt < self._max_retries and not self._backoff(attempt):
                    continue
                return

            if 200 <= status < 300:
                sub.record_success(status)
                self._save()
                self._maybe_expire(sub)
                return
            if 300 <= status < 400:
                sub.record_failure(f"redirect ({status}) refused", http_status=status)
                self._save()
                return
            if status >= 500:
                sub.record_failure(f"receiver {status}", http_status=status)
                self._save()
                if attempt < self._max_retries and not self._backoff(attempt):
                    continue
                return
            # 4xx — client error, do not retry
            sub.record_failure(f"receiver {status}", http_status=status)
            self._save()
            return

    def _backoff(self, attempt: int) -> bool:
        """Interruptible exponential backoff. Returns True if shutdown was
        requested during the wait (caller should stop retrying)."""
        return self._stop.wait(self._retry_base * (2 ** attempt))

    def _maybe_expire(self, sub: Any) -> None:
        # Only SUCCESSFUL deliveries count toward max_fires — a flapping/failing
        # receiver must not self-delete the subscription via its failures.
        if sub.max_fires is not None and sub.stats["successful_fires"] >= sub.max_fires and self._on_expired:
            self._logger.info(f"webhook {sub.subscription_id} auto-expired after {sub.stats['fires']} fires")
            try:
                self._on_expired(sub)
            except Exception:
                self._logger.exception("on_expired callback failed")

    def _save(self) -> None:
        if self._persist:
            try:
                self._persist()
            except Exception:
                self._logger.exception("persist callback failed (contained)")

    # ------------------------------------------------------------------
    # IP-pinned POST
    # ------------------------------------------------------------------

    def _post_pinned(self, url: str, ip: str, headers: Dict[str, str], body: bytes, verify_ssl: bool) -> int:
        """POST to the pre-vetted IP. The TCP socket connects to `ip`; TLS SNI and
        certificate validation use the URL's hostname (not the IP); no redirects."""
        p = urlsplit(url)
        host = p.hostname
        port = p.port or (443 if p.scheme == "https" else 80)
        path = p.path or "/"
        if p.query:
            path += "?" + p.query

        raw = socket.create_connection((ip, port), timeout=self._connect_timeout)
        try:
            raw.settimeout(self._total_timeout)
            if p.scheme == "https":
                ctx = ssl.create_default_context()
                if not verify_ssl:
                    ctx.check_hostname = False
                    ctx.verify_mode = ssl.CERT_NONE
                sock = ctx.wrap_socket(raw, server_hostname=host)   # SNI/cert = hostname
            else:
                sock = raw
            conn = http.client.HTTPConnection(host, port, timeout=self._total_timeout)
            conn.sock = sock                                        # pinned socket; no re-resolve
            try:
                conn.request("POST", path, body=body, headers=headers)
                resp = conn.getresponse()
                status = resp.status
                resp.read()
                return status
            finally:
                conn.close()
        finally:
            try:
                raw.close()
            except OSError:
                pass
