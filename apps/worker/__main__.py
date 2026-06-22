"""Worker process entrypoint.

Usage: python -m apps.worker

Runs:
- APScheduler with all scheduled jobs
- Continuous outbox relay loop (promotes events from outbox to event_log)
- Signal handlers for clean shutdown (SIGTERM/SIGINT)
"""

from __future__ import annotations

import signal
import sys
from threading import Event
from typing import TYPE_CHECKING

import structlog

from apps.common.settings import get_settings
from apps.worker import create_worker

if TYPE_CHECKING:
    from types import FrameType

log = structlog.get_logger(__name__)

OUTBOX_RELAY_INTERVAL = 5

_shutdown = Event()


def _signal_handler(signum: int, _frame: FrameType | None) -> None:
    sig_name = signal.Signals(signum).name
    log.info("received_signal", signal=sig_name)
    _shutdown.set()


def _setup_logging() -> None:
    """Configure structlog for the worker process."""
    import logging  # noqa: PLC0415

    settings = get_settings()

    log_level_map = {
        "DEBUG": logging.DEBUG,
        "INFO": logging.INFO,
        "WARNING": logging.WARNING,
        "ERROR": logging.ERROR,
        "CRITICAL": logging.CRITICAL,
    }
    level = log_level_map.get(settings.log_level.upper(), logging.INFO)

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.dev.ConsoleRenderer()
            if settings.app_env == "dev"
            else structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(level),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )


def _run_outbox_relay() -> None:
    """Run one pass of the outbox relay. Returns early if no DB configured."""
    settings = get_settings()
    if not settings.database_url:
        return

    try:
        from sqlalchemy import create_engine  # noqa: PLC0415
        from sqlalchemy.orm import Session  # noqa: PLC0415
        from sqlalchemy.pool import NullPool  # noqa: PLC0415

        from trading.application.common.event_bus import EventBus  # noqa: PLC0415
        from trading.application.common.outbox_relay import OutboxRelay  # noqa: PLC0415

        sync_url = settings.database_url
        if "+psycopg_async" in sync_url:
            sync_url = sync_url.replace("+psycopg_async", "+psycopg")
        elif "postgresql://" in sync_url and "+psycopg" not in sync_url:
            sync_url = sync_url.replace("postgresql://", "postgresql+psycopg://")

        engine = create_engine(sync_url, poolclass=NullPool)
        bus = EventBus()

        def session_factory() -> Session:
            return Session(engine)

        relay = OutboxRelay(session_factory=session_factory, bus=bus)
        published = relay.run_once()
        if published > 0:
            log.info("outbox_relay", published=published)

        engine.dispose()
    except Exception:
        log.exception("outbox_relay_error")


def main() -> int:
    """Worker entrypoint."""
    _setup_logging()

    signal.signal(signal.SIGTERM, _signal_handler)
    signal.signal(signal.SIGINT, _signal_handler)

    log.info("worker_starting")

    scheduler = create_worker(start=True)
    jobs = scheduler.get_jobs()
    log.info("scheduler_started", job_count=len(jobs), jobs=[j.id for j in jobs])

    try:
        while not _shutdown.is_set():
            _run_outbox_relay()
            _shutdown.wait(timeout=OUTBOX_RELAY_INTERVAL)
    except KeyboardInterrupt:
        log.info("keyboard_interrupt")
    finally:
        log.info("worker_shutting_down")
        scheduler.shutdown(wait=True)
        log.info("worker_stopped")

    return 0


if __name__ == "__main__":
    sys.exit(main())
