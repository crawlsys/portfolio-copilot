"""Pure parsing helpers for Quiver congressional trade responses."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterable, Mapping
from datetime import date, datetime

from dateutil import parser as date_parser

from trading.adapters.quiver.exceptions import QuiverParseError
from trading.domain import (
    Chamber,
    FilingId,
    Member,
    MemberId,
    Party,
    Symbol,
    TradeDisclosure,
    TransactionType,
)

JsonRecord = Mapping[str, object]

_MONEY_RE = re.compile(r"\$?\s*([0-9][0-9,]*)")
_EMPTY_SYMBOLS = {"", "-", "--", "N/A", "NA", "NONE", "NULL"}
_EMPTY_RANGES = {"", "-", "--", "N/A", "NA", "NONE", "NULL", "UNDISCLOSED"}


def extract_records(payload: object) -> tuple[JsonRecord, ...]:
    """Return a tuple of record mappings from common API response envelopes."""

    if isinstance(payload, list):
        return _records_from_iterable(payload)
    if not isinstance(payload, Mapping):
        msg = f"Expected response list or object, got {type(payload).__name__}"
        raise QuiverParseError(msg)

    for key in ("results", "trades"):
        value = payload.get(key)
        if isinstance(value, list):
            return _records_from_iterable(value)

    data = payload.get("data")
    if isinstance(data, list):
        return _records_from_iterable(data)
    if isinstance(data, Mapping):
        for key in ("results", "trades"):
            value = data.get(key)
            if isinstance(value, list):
                return _records_from_iterable(value)

    msg = "Could not find a record array in Quiver response"
    raise QuiverParseError(msg)


def parse_trade_disclosures(records: Iterable[JsonRecord]) -> tuple[TradeDisclosure, ...]:
    """Parse records, skipping malformed rows."""

    disclosures: list[TradeDisclosure] = []
    for record in records:
        try:
            disclosures.append(parse_trade_disclosure(record))
        except QuiverParseError:
            continue
    return tuple(disclosures)


def parse_trade_disclosure(record: JsonRecord) -> TradeDisclosure:
    """Parse a Quiver trade record into the domain disclosure type."""

    member_name = _required_string(record, "Name", "Representative", "Senator")
    bioguide_id = _optional_string(record, "BioGuideID", "BioguideID", "bioguide_id")
    member_id = MemberId(bioguide_id or _synthetic_member_id(member_name))

    transaction_date = parse_quiver_date(
        _required_field(record, "Traded", "TransactionDate", "Date")
    )
    disclosure_date = parse_quiver_date(_required_field(record, "Filed", "Disclosed", "ReportDate"))

    amount_low, amount_high = parse_dollar_range(
        _optional_field(record, "Range", "Trade_Size", "Trade_Size_USD", "TradeSize", "Amount")
    )
    symbol = parse_symbol(_optional_string(record, "Ticker", "Symbol"))
    asset_description = (
        _optional_string(record, "Description", "Company", "Asset", "AssetDescription")
        or _optional_string(record, "TickerType")
        or (symbol.ticker if symbol is not None else "")
    )

    return TradeDisclosure(
        filing_id=FilingId(_synthetic_filing_id(record)),
        member_id=member_id,
        member_name=member_name,
        symbol=symbol,
        asset_description=asset_description,
        transaction_type=parse_transaction_type(_optional_string(record, "Transaction", "Type")),
        transaction_date=transaction_date,
        disclosure_date=disclosure_date,
        amount_range_low=amount_low,
        amount_range_high=amount_high,
        raw_blob_key=None,
    )


def parse_members(records: Iterable[JsonRecord]) -> tuple[Member, ...]:
    """Parse records, skipping malformed member rows."""

    members: list[Member] = []
    for record in records:
        try:
            members.append(parse_member(record))
        except QuiverParseError:
            continue
    return tuple(members)


def parse_member(record: JsonRecord) -> Member:
    """Parse a Quiver politician record into a domain member."""

    name = _required_string(record, "Name", "Representative", "Senator")
    bioguide_id = _optional_string(record, "BioGuideID", "BioguideID", "bioguide_id")
    candidate_id = _optional_string(record, "CandidateID", "candidate_id")
    chamber = parse_chamber(_required_field(record, "Chamber", "House", "Senate"))
    return Member(
        member_id=MemberId(bioguide_id or candidate_id or _synthetic_member_id(name)),
        name=name,
        chamber=chamber,
        party=parse_party(_optional_string(record, "Party")),
        state=_optional_string(record, "State"),
        district=_optional_string(record, "District"),
        committees=frozenset(),
        bioguide_id=bioguide_id,
    )


def parse_dollar_range(value: object) -> tuple[int | None, int | None]:
    """Parse Quiver congressional amount strings into inclusive USD bounds."""

    if value is None:
        return None, None
    text = str(value).strip()
    if text.upper() in _EMPTY_RANGES:
        return None, None

    numbers = [_parse_money(match.group(1)) for match in _MONEY_RE.finditer(text)]
    if not numbers:
        msg = f"Could not parse dollar range: {text!r}"
        raise QuiverParseError(msg)

    lowered = text.casefold()
    if "over" in lowered or "more than" in lowered or lowered.startswith((">", "$>")):
        return numbers[0], None
    if text.endswith("+"):
        return numbers[0], None
    if len(numbers) == 1:
        return numbers[0], None
    return numbers[0], numbers[1]


def parse_transaction_type(value: str | None) -> TransactionType:
    """Map Quiver transaction labels to the domain enum."""

    if value is None:
        return TransactionType.OTHER
    normalized = value.strip().casefold()
    if "partial" in normalized and "sale" in normalized:
        return TransactionType.SALE_PARTIAL
    if "purchase" in normalized or normalized in {"buy", "bought"}:
        return TransactionType.PURCHASE
    if "sale" in normalized or normalized in {"sell", "sold"}:
        return TransactionType.SALE
    if "exchange" in normalized:
        return TransactionType.EXCHANGE
    return TransactionType.OTHER


def parse_symbol(value: str | None) -> Symbol | None:
    """Parse a ticker when Quiver reports one; return None for non-public assets."""

    if value is None:
        return None
    raw_ticker = value.strip().upper()
    if raw_ticker in _EMPTY_SYMBOLS:
        return None
    ticker = raw_ticker.replace("/", ".")
    try:
        return Symbol(ticker)
    except ValueError:
        return None


def parse_quiver_date(value: object) -> date:
    """Parse Quiver ISO/date-time strings into date-only domain values."""

    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if not isinstance(value, str):
        msg = f"Expected date string, got {type(value).__name__}"
        raise QuiverParseError(msg)

    text = value.strip()
    if not text:
        raise QuiverParseError("Date value is empty")
    if re.fullmatch(r"\d{8}", text):
        return datetime.strptime(text, "%Y%m%d").date()
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).date()
    except ValueError:
        try:
            return date_parser.parse(text).date()
        except (TypeError, ValueError) as exc:
            msg = f"Could not parse date: {value!r}"
            raise QuiverParseError(msg) from exc


def parse_party(value: str | None) -> Party:
    if value is None:
        return Party.UNKNOWN
    normalized = value.strip().casefold()
    if normalized in {"d", "dem", "democrat", "democratic", "democratic party"}:
        return Party.DEMOCRAT
    if normalized in {"r", "rep", "republican", "republican party", "gop"}:
        return Party.REPUBLICAN
    if normalized in {"i", "ind", "independent"}:
        return Party.INDEPENDENT
    return Party.UNKNOWN


def parse_chamber(value: object) -> Chamber:
    if isinstance(value, bool):
        return Chamber.HOUSE if value else Chamber.SENATE
    if not isinstance(value, str):
        msg = f"Expected chamber string, got {type(value).__name__}"
        raise QuiverParseError(msg)

    normalized = value.strip().casefold()
    if normalized in {"house", "representative", "representatives", "u.s. representatives"}:
        return Chamber.HOUSE
    if normalized in {"senate", "senator", "u.s. senate"}:
        return Chamber.SENATE
    msg = f"Unknown chamber: {value!r}"
    raise QuiverParseError(msg)


def _records_from_iterable(values: Iterable[object]) -> tuple[JsonRecord, ...]:
    records: list[JsonRecord] = []
    for value in values:
        if isinstance(value, Mapping):
            records.append(value)
    return tuple(records)


def _required_field(record: JsonRecord, *names: str) -> object:
    value = _optional_field(record, *names)
    if value is None:
        msg = f"Missing required field; tried {', '.join(names)}"
        raise QuiverParseError(msg)
    return value


def _optional_field(record: JsonRecord, *names: str) -> object | None:
    for name in names:
        value = record.get(name)
        if value is not None:
            return value
    return None


def _required_string(record: JsonRecord, *names: str) -> str:
    value = _optional_string(record, *names)
    if value is None:
        msg = f"Missing required string field; tried {', '.join(names)}"
        raise QuiverParseError(msg)
    return value


def _optional_string(record: JsonRecord, *names: str) -> str | None:
    value = _optional_field(record, *names)
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _parse_money(value: str) -> int:
    return int(value.replace(",", ""))


def _synthetic_member_id(name: str) -> str:
    digest = hashlib.sha256(name.strip().casefold().encode("utf-8")).hexdigest()[:12]
    return f"quiver-member:{digest}"


def _synthetic_filing_id(record: JsonRecord) -> str:
    payload = json.dumps(record, sort_keys=True, default=str)
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:20]
    return f"quiver-filing:{digest}"
