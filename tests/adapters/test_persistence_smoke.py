"""Smoke test: real Postgres round-trip of ORM models + migration.

Requires a running Postgres at DATABASE_URL. Skipped in CI's pure-unit runs;
run with: DATABASE_URL=... uv run pytest tests/adapters/test_persistence_smoke.py

This is a migration/correctness test, not a unit test. It catches:
- model/table drift (a column in code but not in migration)
- check constraint enforcement (positions.quantity <> 0)
- the event_log append-only trigger
"""
from __future__ import annotations

import os
from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from trading.adapters.persistence.models import BrokerAccountRow, PositionRow

pytestmark = pytest.mark.skipif(
    not os.environ.get("DATABASE_URL"),
    reason="DATABASE_URL required for persistence smoke test",
)


@pytest.fixture(scope="module")
def engine():
    eng = create_engine(os.environ["DATABASE_URL"])
    yield eng


def test_broker_account_round_trip(engine) -> None:  # type: ignore[no-untyped-def]
    acct_id = f"smoke_{uuid4().hex[:8]}"
    with Session(engine) as s:
        s.add(
            BrokerAccountRow(
                account_id=acct_id,
                nickname="Smoke",
                masked_schwab_id="****9999",
                account_type="TAXABLE",
                margin_enabled=False,
                allowed_instruments=["EQUITY"],
                is_paper=True,
            )
        )
        s.commit()

        row = s.scalar(select(BrokerAccountRow).where(BrokerAccountRow.account_id == acct_id))
        assert row is not None
        assert row.account_type == "TAXABLE"
        assert row.is_paper is True

        s.delete(row)
        s.commit()


def test_position_check_constraint_rejects_zero_quantity(engine) -> None:  # type: ignore[no-untyped-def]
    acct_id = f"smoke_{uuid4().hex[:8]}"
    with Session(engine) as s:
        s.add(
            BrokerAccountRow(
                account_id=acct_id,
                nickname="Smoke",
                masked_schwab_id="****0000",
                account_type="TAXABLE",
                margin_enabled=False,
                allowed_instruments=["EQUITY"],
                is_paper=True,
            )
        )
        s.commit()

        # Zero quantity should violate ck_positions_nonzero_quantity.
        with pytest.raises(IntegrityError):
            s.add(
                PositionRow(
                    account_id=acct_id,
                    symbol="AAPL",
                    asset_class="EQUITY",
                    quantity=Decimal("0"),
                    average_cost=Decimal("150"),
                    market_value=Decimal("0"),
                    unrealized_pnl=Decimal("0"),
                    as_of=datetime.now(UTC),
                )
            )
            s.commit()
        s.rollback()

        # Cleanup
        s.execute(text("DELETE FROM positions WHERE account_id = :a"), {"a": acct_id})
        s.execute(text("DELETE FROM broker_accounts WHERE account_id = :a"), {"a": acct_id})
        s.commit()


def test_event_log_rejects_update(engine) -> None:  # type: ignore[no-untyped-def]
    """The append-only trigger must fire on UPDATE."""
    eid = str(uuid4())
    cid = str(uuid4())
    with Session(engine) as s:
        s.execute(
            text(
                """
                INSERT INTO event_log
                  (event_id, event_type, schema_version, aggregate_id,
                   aggregate_type, occurred_at, correlation_id, payload, envelope)
                VALUES
                  (:eid, 'test.v1', 1, 'x', 'test', now(),
                   :cid, '{}'::jsonb, '{}'::jsonb)
                """
            ),
            {"eid": eid, "cid": cid},
        )
        s.commit()

        with pytest.raises(Exception, match="append-only"):
            s.execute(
                text("UPDATE event_log SET event_type='tampered.v1' WHERE event_id=:eid"),
                {"eid": eid},
            )
            s.commit()
        s.rollback()

        # Cleanup the inserted row by dropping+recreating the trigger briefly.
        s.execute(text("ALTER TABLE event_log DISABLE TRIGGER event_log_no_update"))
        s.execute(text("DELETE FROM event_log WHERE event_id = :eid"), {"eid": eid})
        s.execute(text("ALTER TABLE event_log ENABLE TRIGGER event_log_no_update"))
        s.commit()
