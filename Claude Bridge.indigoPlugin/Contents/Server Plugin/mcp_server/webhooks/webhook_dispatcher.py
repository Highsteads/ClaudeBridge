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
  * HMAC-SHA256 signing over `timestamp + "." + body`, tight timeouts, and
    interruptible backoff so a plugin reload is clean. Delivery is SERIAL (one
    worker), which is itself the concurrency cap; the unused semaphore that
    claimed otherwise is gone.
  * ONE failure per event. The retries of one event count as one failure
    against the quarantine, recorded after the last attempt — counting each
    attempt quarantined a subscription after little more than one bad event.

Lifecycle: each worker has its OWN stop event. stop() sets the running
worker's; start() drains the queue and starts a fresh worker with a fresh
event, even if the old one is still finishing a delivery. Until 3.0.2 a
disable->enable left a None wake-up sentinel in the queue that killed the new
worker at once, so deliveries stopped for good with no error; and a stop()
whose join timed out made start() return early with the stop flag still set,
so dispatch() silently dropped everything.

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

# How much of a receiver's response body to read before hanging up. Only the
# status code matters to us, so this is purely about not letting a receiver
# decide how much memory we spend.
_RESPONSE_READ_CAP = 64 * 1024


def host_header(url: str) -> str:
    """The Host header for a delivery. HTTPConnection's default port is 80, so
    left to itself it sent "Host: example.com:443" on https — legal but unusual,
    and some receivers and proxies route on the exact string. The port is named
    only when it is not the scheme's default."""
    p = urlsplit(url)
    host = p.hostname or ""
    out = f"[{host}]" if ":" in host else host
    if p.port and p.port != (443 if p.scheme == "https" else 80):
        out += f":{p.port}"
    return out


class WebhookDispatcher:
    """Async, SSRF-revalidating, IP-pinning webhook delivery."""

    def __init__(
        self,
        allowlist_provider: Callable[[], Any],
        logger: Optional[logging.Logger] = None,
        on_expired: Optional[Callable[[Any], None]] = None,
        persist: Optional[Callable[[], None]] = None,
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
        # The CURRENT worker's stop event. Replaced by every start().
        self._stop = threading.Event()
        self._lifecycle = threading.Lock()
        self._tls = threading.local()    # .stop = the event of the worker on this thread
        self._recent: list = []          # delivery timestamps, for the rate cap
        self._rate_lock = threading.Lock()

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self) -> None:
        with self._lifecycle:
            if self._worker and self._worker.is_alive() and not self._stop.is_set():
                return                      # already running
            if self._worker is not None:
                # A restart. Anything still queued belongs to the run that was
                # stopped: stale events (their conditions may no longer hold,
                # which is why a disable also cancels the dwell timers) and
                # the None wake-up.
                self._drain_queue()
            # A fresh event for the new worker. An old worker still finishing
            # a delivery keeps its own, already set, and exits after it.
            stop = threading.Event()
            self._stop = stop
            self._worker = threading.Thread(
                target=self._worker_loop, args=(stop,), name="webhook-dispatcher", daemon=True
            )
            self._worker.start()

    def stop(self, wait: bool = True) -> None:
        """Stop the worker. wait=False signals it and returns at once, joining
        on a short helper thread instead — for a caller on Indigo's dispatch
        thread (a Configure save), which must not be held for up to 17 s."""
        with self._lifecycle:
            self._stop.set()
            worker = self._worker
        try:
            self._queue.put_nowait(None)   # best-effort wake; the worker also polls its event
        except queue.Full:
            pass
        if not (worker and worker.is_alive()):
            return
        if wait:
            self._join(worker)
        else:
            threading.Thread(target=self._join, args=(worker,),
                             name="webhook-dispatcher-stop", daemon=True).start()

    def _join(self, worker: threading.Thread) -> None:
        # Join budget must exceed the worst-case single in-flight delivery
        # (connect + total socket timeout) or the worker can be left orphaned
        # mid-delivery on a plugin reload (the IndigoPluginHost3 orphan gotcha).
        worker.join(timeout=self._connect_timeout + self._total_timeout + 2)
        if worker.is_alive():
            self._logger.warning("webhook-dispatcher worker still alive after join budget")

    def _drain_queue(self) -> None:
        while True:
            try:
                self._queue.get_nowait()
            except queue.Empty:
                return

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

    def _worker_loop(self, stop: Optional[threading.Event] = None) -> None:
        stop = stop or self._stop
        self._tls.stop = stop
        while not stop.is_set():
            try:
                item = self._queue.get(timeout=1.0)
            except queue.Empty:
                continue
            if item is None:
                # A wake-up. Only THIS worker's stop ends it: a sentinel left
                # behind by an earlier stop() must not kill a newer worker.
                continue
            if stop.is_set():
                # Stopped while waiting: this event belongs to whoever runs
                # next, so hand it back rather than deliver it on the way out.
                try:
                    self._queue.put_nowait(item)
                except queue.Full:
                    pass
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
        # Pre-send drop paths record the failure in memory but do NOT persist —
        # under a storm they would each rewrite the whole store, and the in-memory
        # quarantine still kicks in after 5 attributable fails.

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

        # 3. GLOBAL rate cap — checked LAST of the pre-send gates so a token is
        # only spent on a request actually about to go on the wire (a request
        # dropped for egress/body never charges the shared budget). The cap is
        # SHARED across subscriptions, so a drop here is NOT attributable to this
        # subscription's target — record it via record_dropped (no quarantine)
        # rather than record_failure, or one busy subscription could disable
        # otherwise-healthy ones by exhausting the global budget.
        if not self._rate_ok():
            sub.record_dropped("global webhook rate cap reached; delivery dropped")
            self._logger.warning(f"webhook {sub.subscription_id}: rate cap hit, dropped")
            return

        # 4. sign
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

        # 5. deliver to the PINNED ip, with retry on 5xx / network error. The
        # whole retry run is ONE event: it records one success or ONE failure,
        # after the last attempt, so QUARANTINE_AFTER counts events.
        pinned = str(vetted[0])
        attempts = self._max_retries + 1
        for attempt in range(attempts):
            retryable = False
            try:
                status = self._post_pinned(sub.webhook_url, pinned, headers, body, sub.verify_ssl)
            except Exception as e:
                error, http_status, retryable = f"delivery error: {e}", None, True
            else:
                if 200 <= status < 300:
                    sub.record_success(status)
                    self._save()
                    self._maybe_expire(sub)
                    return
                http_status = status
                if 300 <= status < 400:
                    error = f"redirect ({status}) refused"
                elif status >= 500:
                    error, retryable = f"receiver {status}", True
                else:
                    error = f"receiver {status}"      # 4xx — client error, do not retry
            if retryable and attempt < attempts - 1 and not self._backoff(attempt):
                continue
            if retryable and attempt > 0:
                error += f" (after {attempt + 1} attempts)"
            sub.record_failure(error, http_status=http_status)
            self._save()
            return

    def _backoff(self, attempt: int) -> bool:
        """Interruptible exponential backoff. Returns True if shutdown was
        requested during the wait (caller should stop retrying)."""
        stop = getattr(self._tls, "stop", None) or self._stop
        return stop.wait(self._retry_base * (2 ** attempt))

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

        # A DEADLINE, not just a socket timeout. settimeout bounds each recv, so
        # a receiver that dribbles a byte every few seconds keeps every single
        # call under the limit and holds this delivery open indefinitely. There
        # is one serial worker, so every other subscription queues behind it, and
        # stop()'s join budget — calculated from connect+total — then orphans the
        # worker on reload.
        deadline = time.monotonic() + self._total_timeout

        def _remaining() -> float:
            left = deadline - time.monotonic()
            if left <= 0:
                raise socket.timeout(
                    f"webhook delivery exceeded {self._total_timeout}s"
                )
            return left

        raw = socket.create_connection((ip, port), timeout=self._connect_timeout)
        try:
            raw.settimeout(_remaining())
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
            send_headers = dict(headers)
            send_headers["Host"] = host_header(url)                 # makes request() skip its own
            try:
                sock.settimeout(_remaining())
                conn.request("POST", path, body=body, headers=send_headers)
                sock.settimeout(_remaining())
                resp = conn.getresponse()
                status = resp.status
                # Read a BOUNDED amount and discard. We only need the status
                # code, and an unbounded read() would pull an arbitrarily large
                # response body into memory on the say-so of the receiver.
                read_budget = _RESPONSE_READ_CAP
                while read_budget > 0:
                    sock.settimeout(_remaining())
                    chunk = resp.read(min(8192, read_budget))
                    if not chunk:
                        break
                    read_budget -= len(chunk)
                return status
            finally:
                conn.close()
        finally:
            try:
                raw.close()
            except OSError:
                pass
