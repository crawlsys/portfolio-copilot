# ruff: noqa: PLC0415  — test isolation pattern
"""Tests for the worker scheduler."""

from __future__ import annotations

import os
from unittest.mock import patch

import pytest
from apps.worker.jobs.generate_briefing import run_briefing_sync
from apps.worker.jobs.ingest_congressional import run_ingest_sync
from apps.worker.jobs.pipeline_health_runner import run_pipeline_health_sync
from apps.worker.jobs.token_canary_runner import run_token_canary_sync

from apps.worker import create_worker


class TestCreateWorker:
    """Tests for create_worker()."""

    def test_creates_scheduler_without_starting(self) -> None:
        """Scheduler can be created without starting it."""

        scheduler = create_worker(start=False)
        assert scheduler is not None
        assert not scheduler.running

    def test_registers_expected_jobs(self) -> None:
        """All expected jobs are registered."""

        scheduler = create_worker(start=False)
        jobs = scheduler.get_jobs()
        job_ids = {j.id for j in jobs}

        expected_jobs = {
            "congressional_ingest_market_hours",
            "congressional_ingest_off_hours",
            "daily_briefing",
            "token_canary_market_hours",
            "pipeline_health",
        }
        assert expected_jobs == job_ids

    def test_can_start_and_stop_scheduler(self) -> None:
        """Scheduler starts and stops cleanly."""

        scheduler = create_worker(start=True)
        assert scheduler.running
        scheduler.shutdown(wait=False)
        assert not scheduler.running

    def test_worker_schedule_false_skips_jobs(self) -> None:
        """WORKER_SCHEDULE=false skips job registration."""

        with patch.dict(os.environ, {"WORKER_SCHEDULE": "false"}):
            scheduler = create_worker(start=False)
            jobs = scheduler.get_jobs()
            assert len(jobs) == 0


class TestJobFunctions:
    """Tests that job functions are callable."""

    def test_ingest_congressional_is_callable(self) -> None:
        """run_ingest_sync is callable."""

        assert callable(run_ingest_sync)

    def test_generate_briefing_is_callable(self) -> None:
        """run_briefing_sync is callable."""

        assert callable(run_briefing_sync)

    def test_token_canary_runner_is_callable(self) -> None:
        """run_token_canary_sync is callable."""

        assert callable(run_token_canary_sync)

    def test_pipeline_health_runner_is_callable(self) -> None:
        """run_pipeline_health_sync is callable."""

        assert callable(run_pipeline_health_sync)


class TestJobExecutionWithMocks:
    """Tests that jobs execute without crashing (mocking external deps)."""

    @pytest.mark.asyncio
    async def test_ingest_skips_without_api_key(self) -> None:
        """Congressional ingest logs warning when API key not set."""
        with patch.dict(os.environ, {"QUIVER_API_KEY": ""}, clear=False):
            from apps.common.settings import get_settings

            get_settings.cache_clear()

            from apps.worker.jobs.ingest_congressional import run_ingest

            await run_ingest()

    @pytest.mark.asyncio
    async def test_briefing_skips_without_database(self) -> None:
        """Briefing logs warning when database not set."""
        with patch.dict(os.environ, {"DATABASE_URL": ""}, clear=False):
            from apps.common.settings import get_settings

            get_settings.cache_clear()

            from apps.worker.jobs.generate_briefing import run_briefing

            await run_briefing()

    def test_token_canary_skips_without_schwab(self) -> None:
        """Token canary skips when Schwab not configured."""
        with patch.dict(
            os.environ,
            {"BROKER_MODE": "fake", "SCHWAB_CLIENT_ID": ""},
            clear=False,
        ):
            from apps.common.settings import get_settings

            get_settings.cache_clear()

            from apps.worker.jobs.token_canary_runner import run_token_canary_sync

            run_token_canary_sync()

    def test_pipeline_health_skips_without_database(self) -> None:
        """Pipeline health skips when database not set."""
        with patch.dict(os.environ, {"DATABASE_URL": ""}, clear=False):
            from apps.common.settings import get_settings

            get_settings.cache_clear()

            from apps.worker.jobs.pipeline_health_runner import run_pipeline_health_sync

            run_pipeline_health_sync()
