"""Congressional disclosure query routes."""

from __future__ import annotations

from datetime import UTC, date, datetime, time
from decimal import Decimal

from fastapi import APIRouter, HTTPException, Query, Request, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy import Select, desc, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.common.composition import Composition, session_factory
from trading.adapters.persistence.models import (
    MemberRow,
    PositionRow,
    QuoteCacheRow,
    TradeDisclosureRow,
)
from trading.domain import Symbol

# ruff: noqa: N815 (camelCase keys are intentional for frontend JSON conventions)

router = APIRouter()


class MemberSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    memberId: str
    name: str
    chamber: str
    party: str
    state: str | None
    district: str | None
    committees: list[str]


class DisclosureSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    filingId: str
    memberId: str
    memberName: str
    member: MemberSummary | None
    symbol: str | None
    assetClass: str | None
    assetDescription: str
    transactionType: str
    transactionDate: str
    disclosureDate: str
    amountRangeLow: int | None
    amountRangeHigh: int | None
    lagDays: int


class DisclosureDetail(DisclosureSummary):
    currentPrice: str | None
    inPortfolio: bool
    rawBlobKey: str | None
    ingestedAt: str
    recentMemberDisclosures: list[DisclosureSummary]


class MemberDetail(MemberSummary):
    recentDisclosures: list[DisclosureSummary]


class PortfolioPositionSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    symbol: str
    quantity: str
    marketValue: str


class PortfolioOverlapItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    symbol: str
    position: PortfolioPositionSummary
    memberCount: int
    disclosures: list[DisclosureSummary]


DisclosureRow = tuple[TradeDisclosureRow, MemberRow | None]


@router.get("/disclosures", response_model=list[DisclosureSummary])
async def list_disclosures(
    request: Request,
    member: str | None = None,
    symbol: str | None = None,
    since: date | None = None,
    limit: int = Query(default=50, ge=1, le=200),
) -> list[DisclosureSummary]:
    """Return recent disclosures with optional member, ticker, and date filters."""
    comp = _require_database(request)
    async with session_factory(comp) as session:
        stmt = _disclosure_select()
        stmt = _apply_disclosure_filters(stmt, member=member, symbol=symbol, since=since)
        stmt = stmt.order_by(desc(TradeDisclosureRow.disclosure_date), desc(TradeDisclosureRow.id))
        stmt = stmt.limit(limit)
        rows = (await session.execute(stmt)).all()

    return [_disclosure_to_summary(disclosure, member_row) for disclosure, member_row in rows]


@router.get("/disclosures/{filing_id}", response_model=DisclosureDetail)
async def get_disclosure(filing_id: str, request: Request) -> DisclosureDetail:
    """Return full disclosure detail, including portfolio and quote context."""
    comp = _require_database(request)
    async with session_factory(comp) as session:
        result = await session.execute(
            _disclosure_select().where(TradeDisclosureRow.filing_id == filing_id)
        )
        row = result.one_or_none()
        if row is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Unknown disclosure: {filing_id}",
            )
        disclosure, member_row = row
        portfolio = await _portfolio_positions(comp, session)
        current_price = await _current_price(comp, session, disclosure.symbol)
        recent_rows = (
            await session.execute(
                _disclosure_select()
                .where(TradeDisclosureRow.member_id == disclosure.member_id)
                .where(TradeDisclosureRow.filing_id != disclosure.filing_id)
                .order_by(
                    desc(TradeDisclosureRow.disclosure_date),
                    desc(TradeDisclosureRow.id),
                )
                .limit(8)
            )
        ).all()

    summary = _disclosure_to_summary(disclosure, member_row)
    return DisclosureDetail(
        **summary.model_dump(),
        currentPrice=str(current_price) if current_price is not None else None,
        inPortfolio=bool(disclosure.symbol and disclosure.symbol.upper() in portfolio),
        rawBlobKey=disclosure.raw_blob_key,
        ingestedAt=_iso(disclosure.ingested_at),
        recentMemberDisclosures=[
            _disclosure_to_summary(recent, recent_member) for recent, recent_member in recent_rows
        ],
    )


@router.get("/members", response_model=list[MemberSummary])
async def list_members(request: Request) -> list[MemberSummary]:
    """Return congressional member reference data."""
    comp = _require_database(request)
    async with session_factory(comp) as session:
        rows = (
            await session.execute(
                select(MemberRow).order_by(MemberRow.chamber.asc(), MemberRow.name.asc())
            )
        ).scalars()
    return [_member_to_summary(row) for row in rows]


@router.get("/members/{member_id}", response_model=MemberDetail)
async def get_member(member_id: str, request: Request) -> MemberDetail:
    """Return one member and their recent disclosures."""
    comp = _require_database(request)
    async with session_factory(comp) as session:
        member_row = await session.get(MemberRow, member_id)
        if member_row is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Unknown member: {member_id}",
            )
        disclosure_rows = (
            await session.execute(
                _disclosure_select()
                .where(TradeDisclosureRow.member_id == member_id)
                .order_by(
                    desc(TradeDisclosureRow.disclosure_date),
                    desc(TradeDisclosureRow.id),
                )
                .limit(25)
            )
        ).all()

    summary = _member_to_summary(member_row)
    return MemberDetail(
        **summary.model_dump(),
        recentDisclosures=[
            _disclosure_to_summary(disclosure, disclosure_member)
            for disclosure, disclosure_member in disclosure_rows
        ],
    )


@router.get("/portfolio-overlap", response_model=list[PortfolioOverlapItem])
async def get_portfolio_overlap(
    request: Request,
    limit: int = Query(default=100, ge=1, le=300),
) -> list[PortfolioOverlapItem]:
    """Return recent Congressional disclosures that touch current portfolio tickers."""
    comp = _require_database(request)
    async with session_factory(comp) as session:
        positions = await _portfolio_positions(comp, session)
        if not positions:
            return []

        rows = (
            await session.execute(
                _disclosure_select()
                .where(TradeDisclosureRow.symbol.in_(sorted(positions)))
                .order_by(
                    TradeDisclosureRow.symbol.asc(),
                    desc(TradeDisclosureRow.disclosure_date),
                    desc(TradeDisclosureRow.id),
                )
                .limit(limit)
            )
        ).all()

    grouped: dict[str, list[DisclosureSummary]] = {}
    for disclosure, member_row in rows:
        if disclosure.symbol is None:
            continue
        grouped.setdefault(disclosure.symbol.upper(), []).append(
            _disclosure_to_summary(disclosure, member_row)
        )

    return [
        PortfolioOverlapItem(
            symbol=symbol,
            position=position,
            memberCount=len({d.memberId for d in disclosures}),
            disclosures=disclosures,
        )
        for symbol, position in sorted(positions.items())
        if (disclosures := grouped.get(symbol))
    ]


def _require_database(request: Request) -> Composition:
    comp: Composition = request.app.state.composition
    if comp.engine is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="DATABASE_URL not configured; congressional queries require persistence.",
        )
    return comp


def _disclosure_select() -> Select[tuple[TradeDisclosureRow, MemberRow]]:
    return select(TradeDisclosureRow, MemberRow).outerjoin(
        MemberRow,
        MemberRow.member_id == TradeDisclosureRow.member_id,
    )


def _apply_disclosure_filters(
    stmt: Select[tuple[TradeDisclosureRow, MemberRow]],
    *,
    member: str | None,
    symbol: str | None,
    since: date | None,
) -> Select[tuple[TradeDisclosureRow, MemberRow]]:
    if member:
        member_query = f"%{member.strip().lower()}%"
        stmt = stmt.where(
            or_(
                func.lower(TradeDisclosureRow.member_id).like(member_query),
                func.lower(TradeDisclosureRow.member_name).like(member_query),
                func.lower(MemberRow.name).like(member_query),
            )
        )
    if symbol:
        stmt = stmt.where(func.upper(TradeDisclosureRow.symbol) == symbol.strip().upper())
    if since:
        stmt = stmt.where(
            TradeDisclosureRow.disclosure_date >= datetime.combine(since, time.min, tzinfo=UTC)
        )
    return stmt


async def _portfolio_positions(
    comp: Composition,
    session: AsyncSession,
) -> dict[str, PortfolioPositionSummary]:
    positions: dict[str, tuple[Decimal, Decimal]] = {}

    try:
        accounts = await comp.broker.get_accounts()
        for account in accounts:
            for position in await comp.broker.get_positions(account.account_id):
                symbol = position.symbol.ticker.upper()
                quantity, market_value = positions.get(symbol, (Decimal("0"), Decimal("0")))
                positions[symbol] = (
                    quantity + position.quantity,
                    market_value + position.market_value.amount,
                )
    except Exception:
        positions = {}

    db_rows = (
        await session.execute(
            select(PositionRow.symbol, PositionRow.quantity, PositionRow.market_value)
        )
    ).all()
    for symbol_raw, quantity_raw, market_value_raw in db_rows:
        symbol = str(symbol_raw).upper()
        quantity, market_value = positions.get(symbol, (Decimal("0"), Decimal("0")))
        positions[symbol] = (
            quantity + Decimal(str(quantity_raw)),
            market_value + Decimal(str(market_value_raw)),
        )

    return {
        symbol: PortfolioPositionSummary(
            symbol=symbol,
            quantity=str(quantity),
            marketValue=str(market_value),
        )
        for symbol, (quantity, market_value) in positions.items()
    }


async def _current_price(
    comp: Composition,
    session: AsyncSession,
    symbol: str | None,
) -> Decimal | None:
    if not symbol:
        return None
    normalized = symbol.upper()
    try:
        quote = await comp.broker.get_quote(Symbol(normalized))
        return Decimal(str(quote.last))
    except (KeyError, ValueError):
        pass

    quote_cache = await session.get(QuoteCacheRow, normalized)
    return Decimal(str(quote_cache.last)) if quote_cache is not None else None


def _disclosure_to_summary(
    disclosure: TradeDisclosureRow,
    member: MemberRow | None,
) -> DisclosureSummary:
    transaction_date = disclosure.transaction_date
    disclosure_date = disclosure.disclosure_date
    return DisclosureSummary(
        filingId=disclosure.filing_id,
        memberId=disclosure.member_id,
        memberName=member.name if member else disclosure.member_name,
        member=_member_to_summary(member) if member else None,
        symbol=disclosure.symbol,
        assetClass=disclosure.asset_class,
        assetDescription=disclosure.asset_description,
        transactionType=disclosure.transaction_type,
        transactionDate=_iso(transaction_date),
        disclosureDate=_iso(disclosure_date),
        amountRangeLow=disclosure.amount_range_low,
        amountRangeHigh=disclosure.amount_range_high,
        lagDays=(disclosure_date.date() - transaction_date.date()).days,
    )


def _member_to_summary(member: MemberRow) -> MemberSummary:
    return MemberSummary(
        memberId=member.member_id,
        name=member.name,
        chamber=member.chamber,
        party=member.party,
        state=member.state,
        district=member.district,
        committees=_string_list(member.committees),
    )


def _string_list(value: object) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value]
    if isinstance(value, tuple):
        return [str(item) for item in value]
    return []


def _iso(value: datetime) -> str:
    return value.isoformat()


__all__ = ["router"]
