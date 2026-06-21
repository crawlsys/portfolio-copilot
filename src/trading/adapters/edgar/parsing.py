"""EDGAR response parsing utilities.

Pure functions that transform raw EDGAR JSON/XML into domain-relevant dicts.
No network calls — just data extraction.
"""

from __future__ import annotations

import logging
import xml.etree.ElementTree as ET  # noqa: S405
from datetime import date
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Mapping

logger = logging.getLogger(__name__)


def normalize_cik(cik: str | int) -> str:
    """Zero-pad a CIK to 10 digits (SEC standard format)."""
    return str(cik).zfill(10)


def parse_ticker_to_cik_map(data: Mapping[str, dict[str, object]]) -> dict[str, str]:
    """Parse the company_tickers.json response into a ticker -> CIK mapping.

    Input shape: {"0": {"cik_str": 1045810, "ticker": "NVDA", "title": "..."}, ...}
    Output: {"NVDA": "0001045810", "AAPL": "0000320193", ...}
    """
    result: dict[str, str] = {}
    for entry in data.values():
        ticker = str(entry.get("ticker", "")).upper()
        cik = entry.get("cik_str")
        if ticker and cik is not None:
            cik_val = int(cik) if isinstance(cik, (int, float)) else str(cik)
            result[ticker] = normalize_cik(cik_val)
    return result


def extract_form4_filings(
    submissions: dict[str, object],
    since: date | None = None,
) -> tuple[dict[str, object], ...]:
    """Extract Form 4 filings from a submissions response.

    Filters by form type '4' and optionally by date.
    Returns minimal filing metadata (accession, date, form).
    """
    filings = submissions.get("filings", {})
    recent = filings.get("recent", {}) if isinstance(filings, dict) else {}

    accession_numbers = recent.get("accessionNumber", [])
    filing_dates = recent.get("filingDate", [])
    forms = recent.get("form", [])
    primary_docs = recent.get("primaryDocument", [])

    if not isinstance(accession_numbers, list):
        return ()

    result: list[dict[str, object]] = []
    for i, form in enumerate(forms):
        if form != "4":
            continue

        filing_date_str = filing_dates[i] if i < len(filing_dates) else None
        if filing_date_str and since:
            try:
                filing_date = date.fromisoformat(filing_date_str)
                if filing_date < since:
                    continue
            except ValueError:
                pass

        result.append(
            {
                "accession_number": accession_numbers[i] if i < len(accession_numbers) else None,
                "filing_date": filing_date_str,
                "form": "4",
                "primary_document": primary_docs[i] if i < len(primary_docs) else None,
            }
        )

    return tuple(result)


TRANSACTION_CODES = {
    "P": "purchase",
    "S": "sale",
    "A": "grant_award",
    "D": "disposition_to_issuer",
    "F": "tax_withholding",
    "I": "discretionary_transaction",
    "M": "exercise_conversion",
    "C": "conversion",
    "E": "expiration_short",
    "H": "expiration_long",
    "O": "out_of_money",
    "X": "in_the_money",
    "G": "gift",
    "L": "small_acquisition",
    "W": "acquisition_will_trust",
    "Z": "voting_trust",
    "J": "other",
    "K": "swap",
    "U": "tender",
}


def parse_transaction_code(code: str) -> str:
    """Map a Form 4 transaction code to a human-readable description."""
    return TRANSACTION_CODES.get(code.upper(), f"unknown_{code}")


def parse_form4_xml(xml_content: str) -> dict[str, object] | None:
    """Parse a Form 4 XML document into structured data.

    Extracts: issuer, owner, transactions (both non-derivative and derivative).
    Returns None if XML is malformed.
    """
    try:
        root = ET.fromstring(xml_content)  # noqa: S314
    except ET.ParseError as e:
        logger.warning("Failed to parse Form 4 XML: %s", e)
        return None

    def get_text(element: ET.Element | None, path: str) -> str | None:
        if element is None:
            return None
        el = element.find(path)
        if el is not None and el.text:
            return el.text.strip()
        value_el = element.find(f"{path}/value")
        if value_el is not None and value_el.text:
            return value_el.text.strip()
        return None

    issuer = root.find("issuer")
    owner = root.find("reportingOwner")
    owner_id = owner.find("reportingOwnerId") if owner is not None else None
    owner_rel = owner.find("reportingOwnerRelationship") if owner is not None else None

    period_of_report = get_text(root, "periodOfReport")

    result: dict[str, object] = {
        "document_type": get_text(root, "documentType"),
        "period_of_report": period_of_report,
        "issuer": {
            "cik": get_text(issuer, "issuerCik"),
            "name": get_text(issuer, "issuerName"),
            "ticker": get_text(issuer, "issuerTradingSymbol"),
        },
        "owner": {
            "cik": get_text(owner_id, "rptOwnerCik") if owner_id is not None else None,
            "name": get_text(owner_id, "rptOwnerName") if owner_id is not None else None,
            "is_officer": (
                get_text(owner_rel, "isOfficer") == "true" if owner_rel is not None else False
            ),
            "is_director": (
                get_text(owner_rel, "isDirector") == "true" if owner_rel is not None else False
            ),
            "officer_title": get_text(owner_rel, "officerTitle") if owner_rel is not None else None,
        },
        "transactions": [],
    }

    transactions: list[dict[str, object]] = []

    for table_name in ("nonDerivativeTable", "derivativeTable"):
        table = root.find(table_name)
        if table is None:
            continue

        is_derivative = table_name == "derivativeTable"
        for txn in table.findall("nonDerivativeTransaction") + table.findall(
            "derivativeTransaction"
        ):
            security_title = get_text(txn, "securityTitle")
            txn_date = get_text(txn, "transactionDate")

            coding = txn.find("transactionCoding")
            txn_code = get_text(coding, "transactionCode") if coding is not None else None

            amounts = txn.find("transactionAmounts")
            shares = get_text(amounts, "transactionShares") if amounts is not None else None
            price = get_text(amounts, "transactionPricePerShare") if amounts is not None else None
            acq_disp = (
                get_text(amounts, "transactionAcquiredDisposedCode")
                if amounts is not None
                else None
            )

            post_amounts = txn.find("postTransactionAmounts")
            shares_after = (
                get_text(post_amounts, "sharesOwnedFollowingTransaction")
                if post_amounts is not None
                else None
            )

            transactions.append(
                {
                    "security_title": security_title,
                    "transaction_date": txn_date,
                    "transaction_code": txn_code,
                    "transaction_type": parse_transaction_code(txn_code) if txn_code else None,
                    "shares": shares,
                    "price_per_share": price,
                    "acquired_disposed": "acquired" if acq_disp == "A" else "disposed",
                    "shares_after": shares_after,
                    "is_derivative": is_derivative,
                }
            )

    result["transactions"] = transactions
    return result


def parse_full_text_search_response(data: dict[str, object]) -> tuple[dict[str, object], ...]:
    """Parse the efts.sec.gov full-text search response.

    Input shape: {"hits": {"hits": [{"_source": {...}, "_score": ...}, ...]}}
    """
    hits_wrapper = data.get("hits", {})
    if not isinstance(hits_wrapper, dict):
        return ()

    hits = hits_wrapper.get("hits", [])
    if not isinstance(hits, list):
        return ()

    results: list[dict[str, object]] = []
    for hit in hits:
        source = hit.get("_source", {})
        results.append(
            {
                "score": hit.get("_score"),
                "ciks": source.get("ciks", []),
                "display_names": source.get("display_names", []),
                "form": source.get("form"),
                "file_date": source.get("file_date"),
                "accession_number": source.get("adsh"),
                "file_type": source.get("file_type"),
                "file_description": source.get("file_description"),
            }
        )

    return tuple(results)
