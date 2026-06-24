# ruff: noqa: PLC0415
"""Tests for the single-job CronJob dispatcher."""

from __future__ import annotations

from unittest.mock import patch

from apps.worker.run_job import JOBS, main


def test_jobs_cover_every_scheduled_job() -> None:
    """The dispatcher must expose a runner for every job that used to run in
    the in-process scheduler (minus the market/off-hours split, which is one
    runner invoked by two CronJobs)."""
    assert set(JOBS) == {
        "daily_briefing",
        "congressional_ingest",
        "token_canary",
        "pipeline_health",
        "vix_alert",
    }


def test_main_unknown_job_returns_2() -> None:
    assert main(["nope"]) == 2


def test_main_no_args_returns_2() -> None:
    assert main([]) == 2


def test_main_dispatches_to_runner() -> None:
    with patch.dict(JOBS, {"daily_briefing": (called := _Flag())}):
        assert main(["daily_briefing"]) == 0
    assert called.fired


class _Flag:
    def __init__(self) -> None:
        self.fired = False

    def __call__(self) -> None:
        self.fired = True
