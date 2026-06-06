"""
Reconciliation engine for the HAMq Arbiter.

The Reconciler is the core of the Arbiter.  It:

1. Fetches the most-recently-sent sequences from each Producer API
2. Fetches the corresponding sequences from the Consumer API
3. Computes the set difference (sent - received) = missing
4. Calculates loss_rate = |missing| / |sent|
5. Persists AuditResult records via AuditStore
6. Updates Prometheus metrics
7. Fires webhook alerts when loss_rate exceeds the threshold
8. Runs continuously in a background asyncio task at RECONCILE_INTERVAL_S

Producer API contract
---------------------
  GET {producer_url}/api/messages/recent
  Query params: limit=N
  Expected response (JSON):
  {
      "producer_id": "producer-1",
      "sequences": [1, 2, 3, ..., N],
      "total": N
  }

Consumer API contract
---------------------
  GET {consumer_url}/api/messages/missing
  Query params: producer_id=X&seq_from=N&seq_to=M
  Expected response (JSON):
  {
      "producer_id": "producer-1",
      "missing": [5, 12, 47],
      "checked_range": [N, M]
  }

Both APIs require Bearer token authentication if the corresponding
PRODUCER_API_TOKEN / CONSUMER_API_TOKEN config values are non-empty.

Error handling
--------------
If a Producer or Consumer API call fails (network error, non-200 status),
the reconcile pass for that producer is skipped with an error log entry and
a counter increment.  The background loop never stops due to a single
producer failure; it retries on the next scheduled interval.
"""

import asyncio
import logging
import time
import uuid
from datetime import datetime, timezone
from typing import Optional

import httpx

from app.audit_store import AuditStore
from app.config import settings
from app.metrics import (
    alert_events_total,
    arbiter_running_gauge,
    loss_rate_gauge,
    missing_messages_total,
    received_gauge,
    reconcile_duration_seconds,
    reconcile_errors_total,
    reconcile_runs_total,
    sent_gauge,
)
from app.models import (
    AlertEvent,
    ArbiterStatus,
    AuditResult,
    ProducerAuditResult,
    ReconcileReport,
)

logger = logging.getLogger(__name__)


def _now_iso() -> str:
    """Return the current UTC time as an ISO-8601 string."""
    return datetime.now(timezone.utc).isoformat()


def _compute_status(
    loss_rate: float,
    threshold: float,
) -> str:
    """
    Map a loss rate fraction to a severity label.

    Rules:
      0.0         → 'ok'
      0 < lr < threshold → 'warning'
      lr >= threshold    → 'critical'
    """
    if loss_rate == 0.0:
        return "ok"
    if loss_rate < threshold:
        return "warning"
    return "critical"


class Reconciler:
    """
    Periodically fetches sent messages from each Producer API and received
    messages from the Consumer API, then computes per-producer loss metrics.

    Lifecycle
    ---------
    reconciler = Reconciler(audit_store)
    await reconciler.start()   # begins the background loop
    report = await reconciler.run_once()   # manual trigger
    await reconciler.stop()    # graceful shutdown
    """

    def __init__(self, audit_store: AuditStore) -> None:
        self._store = audit_store
        self._running = False
        self._task: Optional[asyncio.Task] = None
        self._last_report: Optional[ReconcileReport] = None
        self._last_loss_rate: Optional[float] = None
        self._last_reconcile_at: Optional[str] = None

        self._producer_urls: list[str] = [
            url.strip()
            for url in settings.PRODUCER_API_URLS.split(",")
            if url.strip()
        ]

        self._http: Optional[httpx.AsyncClient] = None
        # Cached tokens — refreshed automatically when a 401 is received
        self._producer_token: str = settings.PRODUCER_API_TOKEN
        self._consumer_token: str = settings.CONSUMER_API_TOKEN

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """
        Start the background reconcile loop.

        Creates a persistent httpx.AsyncClient for connection reuse and
        launches the loop as an asyncio background Task.

        Safe to call multiple times — a second call is a no-op if already running.
        """
        if self._running:
            logger.warning("Reconciler.start() called but loop is already running")
            return

        # Create the shared HTTP client with a generous timeout; each API call
        # may involve DNS resolution plus network round-trip in a multi-cluster setup.
        self._http = httpx.AsyncClient(timeout=httpx.Timeout(30.0))

        self._running = True
        arbiter_running_gauge.set(1)

        self._task = asyncio.create_task(
            self._loop(),
            name="reconciler-loop",
        )
        logger.info(
            "Reconciler started — polling %d producer(s) every %.1fs",
            len(self._producer_urls),
            settings.RECONCILE_INTERVAL_S,
        )

    async def stop(self) -> None:
        """
        Stop the background reconcile loop gracefully.

        Cancels the asyncio task and waits for it to finish, then closes the
        HTTP client.  A subsequent start() call re-creates everything.
        """
        if not self._running:
            return

        self._running = False
        arbiter_running_gauge.set(0)

        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

        if self._http:
            await self._http.aclose()
            self._http = None

        logger.info("Reconciler stopped")

    # ------------------------------------------------------------------
    # Background loop
    # ------------------------------------------------------------------

    async def _loop(self) -> None:
        """
        Background task that calls run_once() on each interval.

        Any exception from run_once() is caught, logged, and counted — the
        loop never exits due to a transient failure.
        """
        while self._running:
            try:
                await self.run_once()
            except asyncio.CancelledError:
                raise  # propagate so stop() can await the task cleanly
            except Exception as exc:
                reconcile_errors_total.inc()
                logger.exception("Reconcile pass failed: %s", exc)

            # Sleep until the next scheduled pass, but wake up immediately if
            # stop() cancels the task.
            try:
                await asyncio.sleep(settings.RECONCILE_INTERVAL_S)
            except asyncio.CancelledError:
                raise

    # ------------------------------------------------------------------
    # Core reconciliation logic
    # ------------------------------------------------------------------

    async def run_once(self) -> ReconcileReport:
        """
        Execute a single reconciliation pass across all configured producers.

        For each producer URL:
          1. Fetch recent sent sequences from the Producer API.
          2. For each distinct producer_id in the response, fetch missing
             sequences from the Consumer API.
          3. Compute loss_rate and build an AuditResult.
          4. Persist the AuditResult and update Prometheus metrics.
          5. Fire an alert if loss_rate >= threshold.

        Returns the ReconcileReport aggregating results across all producers.
        """
        start_ts = _now_iso()
        start_wall = time.monotonic()

        producer_results: list[ProducerAuditResult] = []
        total_sent = 0
        total_received = 0
        total_missing = 0

        # Ensure we have an HTTP client even when called outside start()
        # (e.g., from tests or the manual reconcile endpoint before autostart).
        if self._http is None:
            self._http = httpx.AsyncClient(timeout=httpx.Timeout(30.0))

        for producer_url in self._producer_urls:
            try:
                result = await self._reconcile_producer(producer_url, start_ts)
                if result is not None:
                    producer_results.append(result)
                    total_sent += result.sent_count
                    total_received += result.received_count
                    total_missing += result.missing_count
            except Exception as exc:
                reconcile_errors_total.inc()
                logger.error(
                    "Failed to reconcile producer at %s: %s",
                    producer_url,
                    exc,
                )

        # Compute overall loss rate (guard against zero-division when nothing was sent)
        overall_loss_rate = (total_missing / total_sent) if total_sent > 0 else 0.0

        elapsed_ms = (time.monotonic() - start_wall) * 1000.0

        report = ReconcileReport(
            report_id=str(uuid.uuid4()),
            timestamp=start_ts,
            producers=producer_results,
            total_sent=total_sent,
            total_received=total_received,
            total_missing=total_missing,
            overall_loss_rate=overall_loss_rate,
            duration_ms=round(elapsed_ms, 2),
        )

        # Update in-memory state for status reporting
        self._last_report = report
        self._last_loss_rate = overall_loss_rate
        self._last_reconcile_at = start_ts

        # Record observation in Prometheus histogram and increment run counter
        reconcile_runs_total.inc()
        reconcile_duration_seconds.observe(elapsed_ms / 1000.0)

        logger.info(
            "Reconcile pass complete: %d sent, %d received, %d missing "
            "(%.2f%% loss) in %.0fms",
            total_sent,
            total_received,
            total_missing,
            overall_loss_rate * 100,
            elapsed_ms,
        )

        return report

    async def _reconcile_producer(
        self,
        producer_url: str,
        timestamp: str,
    ) -> Optional[ProducerAuditResult]:
        """
        Reconcile a single producer against the consumer.

        Parameters
        ----------
        producer_url:
            Base URL of the Producer REST API.
        timestamp:
            ISO-8601 string to stamp on the resulting AuditResult.

        Returns
        -------
        ProducerAuditResult or None if the producer API is unreachable.
        """
        # Step 1: fetch sent sequences from the Producer API
        sent_tuples = await self._fetch_producer_sequences(producer_url, "")
        if not sent_tuples:
            logger.warning("No sequences returned from %s — skipping", producer_url)
            return None

        # Group sequences by producer_id (a single API may serve multiple producers
        # if the URL points to an aggregator endpoint)
        by_producer: dict[str, set[int]] = {}
        for (prod_id, seq) in sent_tuples:
            by_producer.setdefault(prod_id, set()).add(seq)

        # For simplicity, take the first (and typically only) producer_id.
        # In multi-producer-per-URL setups, callers should list each producer URL
        # separately so one-to-one reconciliation is maintained.
        producer_id, sent_seqs = next(iter(by_producer.items()))

        if not sent_seqs:
            logger.debug("Empty sequence set for %s — nothing to reconcile", producer_id)
            return None

        # Lag-aware: only compare sequences the consumer has already processed.
        # This prevents false 100% loss reports when the consumer is catching up.
        watermark = await self._fetch_consumer_watermark(producer_id)
        if watermark is not None and watermark > 0:
            eligible = {s for s in sent_seqs if s <= watermark}
            if not eligible:
                logger.debug(
                    "Producer %s: all %d fetched seqs exceed consumer watermark %d — skipping",
                    producer_id, len(sent_seqs), watermark,
                )
                return None
            sent_seqs = eligible

        seq_from = min(sent_seqs)
        seq_to = max(sent_seqs)

        # Step 2: find gaps in the consumer for this producer's sequence range
        received_seqs = await self._fetch_consumer_sequences(seq_from, seq_to, producer_id)

        # Step 3: compute the set difference
        missing_seqs = sorted(sent_seqs - received_seqs)
        sent_count = len(sent_seqs)
        received_count = len(sent_seqs & received_seqs)
        missing_count = len(missing_seqs)

        # Step 4: compute loss rate
        loss_rate = missing_count / sent_count if sent_count > 0 else 0.0
        status = _compute_status(loss_rate, settings.ALERT_LOSS_RATE_THRESHOLD)

        # Step 5: persist to SQLite
        audit_id = str(uuid.uuid4())
        audit_result = AuditResult(
            audit_id=audit_id,
            timestamp=timestamp,
            producer_id=producer_id,
            sent_count=sent_count,
            received_count=received_count,
            missing_sequences=missing_seqs,
            loss_rate=loss_rate,
            status=status,
        )
        await self._store.save_result(audit_result)

        # Step 6: update Prometheus metrics
        loss_rate_gauge.labels(producer_id=producer_id).set(loss_rate)
        sent_gauge.labels(producer_id=producer_id).set(sent_count)
        received_gauge.labels(producer_id=producer_id).set(received_count)
        if missing_count > 0:
            missing_messages_total.labels(producer_id=producer_id).inc(missing_count)

        # Step 7: fire alert if above threshold
        if loss_rate >= settings.ALERT_LOSS_RATE_THRESHOLD and settings.ALERT_LOSS_RATE_THRESHOLD >= 0:
            alert = AlertEvent(
                timestamp=_now_iso(),
                producer_id=producer_id,
                loss_rate=loss_rate,
                missing_count=missing_count,
                threshold=settings.ALERT_LOSS_RATE_THRESHOLD,
            )
            await self._send_alert(alert)
            alert_events_total.labels(producer_id=producer_id).inc()

        return ProducerAuditResult(
            audit_id=audit_id,
            producer_id=producer_id,
            producer_url=producer_url,
            sent_count=sent_count,
            received_count=received_count,
            missing_count=missing_count,
            missing_sequences=missing_seqs,
            loss_rate=loss_rate,
            status=status,
        )

    # ------------------------------------------------------------------
    # Auto-login helpers
    # ------------------------------------------------------------------

    async def _login(self, base_url: str, username: str, password: str) -> str:
        """POST /api/auth/login and return the access token, or empty string on failure."""
        try:
            resp = await self._http.post(
                f"{base_url}/api/auth/login",
                json={"username": username, "password": password},
                timeout=10.0,
            )
            resp.raise_for_status()
            return resp.json().get("access_token", "")
        except Exception as exc:
            logger.error("Auto-login to %s failed: %s", base_url, exc)
            return ""

    async def _ensure_producer_token(self, producer_url: str) -> str:
        if not self._producer_token:
            self._producer_token = await self._login(
                producer_url,
                settings.PRODUCER_API_USERNAME,
                settings.PRODUCER_API_PASSWORD,
            )
        return self._producer_token

    async def _ensure_consumer_token(self) -> str:
        if not self._consumer_token:
            self._consumer_token = await self._login(
                settings.CONSUMER_API_URL,
                settings.CONSUMER_API_USERNAME,
                settings.CONSUMER_API_PASSWORD,
            )
        return self._consumer_token

    # ------------------------------------------------------------------
    # External API fetchers
    # ------------------------------------------------------------------

    async def _fetch_producer_sequences(
        self,
        producer_url: str,
        token: str,
    ) -> set[tuple[str, int]]:
        token = await self._ensure_producer_token(producer_url)
        url = f"{producer_url}/api/messages/recent"
        headers = {"Authorization": f"Bearer {token}"} if token else {}

        try:
            resp = await self._http.get(
                url,
                params={"limit": settings.RECONCILE_LOOKBACK_MESSAGES},
                headers=headers,
            )
            if resp.status_code == 401:
                # Token expired — force refresh and retry once
                self._producer_token = ""
                token = await self._ensure_producer_token(producer_url)
                headers = {"Authorization": f"Bearer {token}"} if token else {}
                resp = await self._http.get(
                    url,
                    params={"limit": settings.RECONCILE_LOOKBACK_MESSAGES},
                    headers=headers,
                )
            resp.raise_for_status()
        except httpx.HTTPStatusError as exc:
            logger.error(
                "Producer API %s returned HTTP %d: %s",
                url, exc.response.status_code, exc.response.text[:200],
            )
            return set()
        except httpx.RequestError as exc:
            logger.error("Network error calling Producer API %s: %s", url, exc)
            return set()

        data = resp.json()
        # Handle list format: [{id, sequence, producer_id, ...}, ...]
        if isinstance(data, list):
            if not data:
                return set()
            producer_id: str = data[0].get("producer_id", "unknown")
            sequences: list[int] = [msg["sequence"] for msg in data if "sequence" in msg]
        else:
            # Handle dict format: {producer_id, sequences, total}
            producer_id = data.get("producer_id", "unknown")
            sequences = data.get("sequences", [])

        return {(producer_id, seq) for seq in sequences}

    async def _fetch_consumer_watermark(self, producer_id: str) -> Optional[int]:
        """
        GET /api/status from the Consumer and return the highest sequence number
        that the consumer has already persisted for *producer_id*.

        Returns None on any error so the caller can fall back to comparing the
        full sent set (i.e., behave as before the lag-aware fix).
        """
        token = await self._ensure_consumer_token()
        url = f"{settings.CONSUMER_API_URL}/api/status"
        headers = {"Authorization": f"Bearer {token}"} if token else {}

        try:
            resp = await self._http.get(url, headers=headers, timeout=10.0)
            if resp.status_code == 401:
                self._consumer_token = ""
                token = await self._ensure_consumer_token()
                headers = {"Authorization": f"Bearer {token}"} if token else {}
                resp = await self._http.get(url, headers=headers, timeout=10.0)
            resp.raise_for_status()
        except httpx.HTTPStatusError as exc:
            logger.warning(
                "Consumer status %s returned HTTP %d — watermark unavailable",
                url, exc.response.status_code,
            )
            return None
        except httpx.RequestError as exc:
            logger.warning("Network error fetching consumer status %s: %s", url, exc)
            return None

        data = resp.json()
        last_by_producer: dict = data.get("last_sequence_by_producer", {})
        watermark = last_by_producer.get(producer_id)
        return int(watermark) if watermark is not None else None

    async def _fetch_consumer_sequences(
        self,
        seq_from: int,
        seq_to: int,
        producer_id: str,
    ) -> set[int]:
        token = await self._ensure_consumer_token()
        url = f"{settings.CONSUMER_API_URL}/api/messages/missing"
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        params = {"producer_id": producer_id, "seq_from": seq_from, "seq_to": seq_to}

        try:
            resp = await self._http.get(url, params=params, headers=headers)
            if resp.status_code == 401:
                self._consumer_token = ""
                token = await self._ensure_consumer_token()
                headers = {"Authorization": f"Bearer {token}"} if token else {}
                resp = await self._http.get(url, params=params, headers=headers)
            resp.raise_for_status()
        except httpx.HTTPStatusError as exc:
            logger.error(
                "Consumer API %s returned HTTP %d: %s",
                url, exc.response.status_code, exc.response.text[:200],
            )
            return set()
        except httpx.RequestError as exc:
            logger.error("Network error calling Consumer API %s: %s", url, exc)
            return set()

        data = resp.json()
        # Consumer returns either List[int] (missing seqs) or {missing: [...]}
        if isinstance(data, list):
            missing_at_consumer: list[int] = data
        else:
            missing_at_consumer = data.get("missing", [])

        full_range = set(range(seq_from, seq_to + 1))
        return full_range - set(missing_at_consumer)

    # ------------------------------------------------------------------
    # Alerting
    # ------------------------------------------------------------------

    async def _send_alert(self, event: AlertEvent) -> None:
        """
        POST an AlertEvent as JSON to the configured webhook URL.

        Failures are logged but never propagate — alerting must not interfere
        with the reconcile loop.

        Parameters
        ----------
        event:
            The alert payload to send.
        """
        if not settings.ALERT_WEBHOOK_URL:
            # No webhook configured; log only
            logger.warning(
                "ALERT: producer=%s loss_rate=%.2f%% missing=%d (threshold=%.2f%%)",
                event.producer_id,
                event.loss_rate * 100,
                event.missing_count,
                event.threshold * 100,
            )
            return

        try:
            resp = await self._http.post(
                settings.ALERT_WEBHOOK_URL,
                json=event.model_dump(),
                headers={"Content-Type": "application/json"},
                timeout=10.0,
            )
            resp.raise_for_status()
            logger.info(
                "Alert webhook delivered for producer %s (loss=%.2f%%)",
                event.producer_id,
                event.loss_rate * 100,
            )
        except Exception as exc:
            # Log but never raise — alerting is best-effort
            logger.error(
                "Failed to deliver alert webhook to %s: %s",
                settings.ALERT_WEBHOOK_URL,
                exc,
            )

    # ------------------------------------------------------------------
    # Status
    # ------------------------------------------------------------------

    def get_status(self) -> ArbiterStatus:
        """
        Return a lightweight snapshot of the Reconciler's operational state.
        Called by GET /api/status and the WebSocket stream.
        """
        # Query the database for total audit count would require an async call;
        # we approximate with 0 here and let the API layer fill in the real count
        # by calling audit_store.get_stats() separately.
        return ArbiterStatus(
            arbiter_id=settings.ARBITER_ID,
            running=self._running,
            last_reconcile_at=self._last_reconcile_at,
            last_loss_rate=self._last_loss_rate,
            producers_monitored=len(self._producer_urls),
            total_audits=0,  # filled by the routes layer from audit_store
        )
