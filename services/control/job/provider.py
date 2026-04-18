"""In-process job provider using a lightweight polling thread.

Satisfies the ``JobProviderAdapter`` protocol without any external
scheduling infrastructure (e.g. Celery). A single daemon thread polls
for the next due job and invokes ``handle_provider_callback`` directly.
"""

from __future__ import annotations

import threading
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from packages.brain_shared.envelope import EnvelopeKind, new_meta
from packages.brain_shared.ids import generate_ulid_str
from packages.brain_shared.logging import get_logger
from services.control.job.component import SERVICE_COMPONENT_ID
from services.control.job.domain import ScheduleType, TriggerSource
from services.control.job.interfaces import ProviderHealthStatus, ProviderJobPayload

if TYPE_CHECKING:
    from services.control.job.interfaces import JobRepository
    from services.control.job.service import JobService

_LOGGER = get_logger(__name__)
_PROVIDER_SOURCE = "job_provider"
_THREAD_NAME = "job-provider"
_STOP_TIMEOUT_SECONDS = 5.0
_PROVIDER_DETAIL_POLLING = "polling"
_PROVIDER_DETAIL_STOPPED = "stopped"


class InProcessJobProvider:
    """Lightweight in-process job provider backed by a single polling thread."""

    def __init__(
        self,
        *,
        poll_interval_seconds: float,
        repository: JobRepository,
    ) -> None:
        self._poll_interval = poll_interval_seconds
        self._repository = repository
        self._service: JobService | None = None
        self._wake = threading.Event()
        self._shutdown = threading.Event()
        self._thread: threading.Thread | None = None

    def set_service(self, service: JobService) -> None:
        """Wire the service reference after construction (breaks circular dep)."""
        self._service = service

    def start(self) -> None:
        """Start the polling daemon thread."""
        if self._thread is not None and self._thread.is_alive():
            return
        self._shutdown.clear()
        self._thread = threading.Thread(
            target=self._poll_loop,
            name=_THREAD_NAME,
            daemon=True,
        )
        self._thread.start()
        _LOGGER.info("InProcessJobProvider started (poll=%.1fs)", self._poll_interval)

    def stop(self) -> None:
        """Signal the polling thread to shut down."""
        self._shutdown.set()
        self._wake.set()
        if self._thread is not None:
            self._thread.join(timeout=_STOP_TIMEOUT_SECONDS)
            self._thread = None
        _LOGGER.info("InProcessJobProvider stopped")

    # ------------------------------------------------------------------
    # JobProviderAdapter protocol
    # ------------------------------------------------------------------

    def register_job(self, *, payload: ProviderJobPayload) -> None:
        """Wake the poll loop so it picks up the new job."""
        self._wake.set()

    def update_job(self, *, payload: ProviderJobPayload) -> None:
        """Wake the poll loop so it picks up updated timing."""
        self._wake.set()

    def pause_job(self, *, job_id: str) -> None:
        """Wake the poll loop (job's next_run_at is already cleared)."""
        self._wake.set()

    def resume_job(self, *, job_id: str) -> None:
        """Wake the poll loop so it picks up the resumed job."""
        self._wake.set()

    def delete_job(self, *, job_id: str) -> None:
        """Wake the poll loop (job is no longer active)."""
        self._wake.set()

    def trigger_now(
        self,
        *,
        job_id: str,
        scheduled_for: datetime,
        trace_id: str,
        trigger_source: str,
    ) -> None:
        """Trigger is handled inline by run_job_now; wake for awareness."""
        self._wake.set()

    def health(self) -> ProviderHealthStatus:
        """Return ready if the daemon thread is alive."""
        alive = self._thread is not None and self._thread.is_alive()
        return ProviderHealthStatus(
            ready=alive,
            detail=_PROVIDER_DETAIL_POLLING if alive else _PROVIDER_DETAIL_STOPPED,
        )

    # ------------------------------------------------------------------
    # Poll loop
    # ------------------------------------------------------------------

    def _poll_loop(self) -> None:
        """Main loop: find next due job, sleep until then, fire callback."""
        while not self._shutdown.is_set():
            try:
                self._poll_once()
            except Exception:  # noqa: BLE001
                _LOGGER.exception("InProcessJobProvider poll error")

            # Determine sleep duration
            sleep_seconds = self._poll_interval
            try:
                next_run = self._repository.get_next_run_time()
                if next_run is not None:
                    delta = (next_run - datetime.now(UTC)).total_seconds()
                    if delta > 0:
                        sleep_seconds = min(delta, self._poll_interval)
                    else:
                        sleep_seconds = 0
            except Exception:  # noqa: BLE001
                pass

            if sleep_seconds > 0:
                self._wake.wait(timeout=sleep_seconds)
                self._wake.clear()

    def _poll_once(self) -> None:
        """Process retry-due executions, then check for and dispatch one due job."""
        if self._service is None:
            return

        now = datetime.now(UTC)
        retry_trace_id = generate_ulid_str()
        retry_meta = new_meta(
            kind=EnvelopeKind.EVENT,
            source=_PROVIDER_SOURCE,
            principal=str(SERVICE_COMPONENT_ID),
            trace_id=retry_trace_id,
        )
        self._service.process_retry_due_jobs(meta=retry_meta)

        job = self._repository.get_next_due_job(now=now)
        if job is None:
            return

        trace_id = generate_ulid_str()
        meta = new_meta(
            kind=EnvelopeKind.EVENT,
            source=_PROVIDER_SOURCE,
            principal=str(SERVICE_COMPONENT_ID),
            trace_id=trace_id,
            parent_id=job.origin_envelope_id,
        )

        _LOGGER.info(
            "Dispatching job callback: job_id=%s trace_id=%s",
            job.id,
            trace_id,
        )

        if job.schedule_type == ScheduleType.conditional:
            self._service.evaluate_conditional_job(
                meta=meta,
                job_id=job.id,
            )
            return

        self._service.handle_provider_callback(
            meta=meta,
            job_id=job.id,
            scheduled_for=now.isoformat(),
            trace_id=trace_id,
            trigger_source=TriggerSource.scheduled.value,
        )
