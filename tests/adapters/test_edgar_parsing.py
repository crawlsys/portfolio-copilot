"""Unit tests for EDGAR parsing utilities."""

from __future__ import annotations

from datetime import date

import pytest

from trading.adapters.edgar import (
    TRANSACTION_CODES,
    extract_form4_filings,
    normalize_cik,
    parse_form4_xml,
    parse_full_text_search_response,
    parse_ticker_to_cik_map,
    parse_transaction_code,
)


class TestNormalizeCik:
    def test_pads_short_cik(self) -> None:
        assert normalize_cik("320193") == "0000320193"

    def test_pads_int_cik(self) -> None:
        assert normalize_cik(320193) == "0000320193"

    def test_already_padded(self) -> None:
        assert normalize_cik("0000320193") == "0000320193"

    def test_single_digit(self) -> None:
        assert normalize_cik("1") == "0000000001"


class TestParseTickerToCikMap:
    def test_parses_standard_format(self) -> None:
        data = {
            "0": {"cik_str": 1045810, "ticker": "NVDA", "title": "NVIDIA CORP"},
            "1": {"cik_str": 320193, "ticker": "AAPL", "title": "Apple Inc."},
        }
        result = parse_ticker_to_cik_map(data)
        assert result["NVDA"] == "0001045810"
        assert result["AAPL"] == "0000320193"

    def test_normalizes_ticker_to_uppercase(self) -> None:
        data = {"0": {"cik_str": 123, "ticker": "test", "title": "Test"}}
        result = parse_ticker_to_cik_map(data)
        assert "TEST" in result
        assert "test" not in result

    def test_skips_entries_without_ticker(self) -> None:
        data = {
            "0": {"cik_str": 123, "title": "No Ticker"},
            "1": {"cik_str": 456, "ticker": "GOOD", "title": "Has Ticker"},
        }
        result = parse_ticker_to_cik_map(data)
        assert len(result) == 1
        assert "GOOD" in result


class TestTransactionCodes:
    @pytest.mark.parametrize(
        ("code", "expected"),
        [
            ("P", "purchase"),
            ("S", "sale"),
            ("A", "grant_award"),
            ("D", "disposition_to_issuer"),
            ("F", "tax_withholding"),
            ("M", "exercise_conversion"),
            ("G", "gift"),
        ],
    )
    def test_known_codes(self, code: str, expected: str) -> None:
        assert parse_transaction_code(code) == expected

    def test_lowercase_normalized(self) -> None:
        assert parse_transaction_code("p") == "purchase"

    def test_unknown_code(self) -> None:
        assert parse_transaction_code("Q") == "unknown_Q"

    def test_all_codes_mapped(self) -> None:
        assert len(TRANSACTION_CODES) >= 19


class TestExtractForm4Filings:
    def test_extracts_form4_only(self) -> None:
        submissions = {
            "filings": {
                "recent": {
                    "accessionNumber": ["acc-1", "acc-2", "acc-3"],
                    "filingDate": ["2026-06-01", "2026-06-02", "2026-06-03"],
                    "form": ["4", "10-K", "4"],
                    "primaryDocument": ["form4.xml", "10k.htm", "form4.xml"],
                }
            }
        }
        result = extract_form4_filings(submissions)
        assert len(result) == 2
        assert result[0]["accession_number"] == "acc-1"
        assert result[1]["accession_number"] == "acc-3"

    def test_filters_by_date(self) -> None:
        submissions = {
            "filings": {
                "recent": {
                    "accessionNumber": ["acc-1", "acc-2", "acc-3"],
                    "filingDate": ["2026-05-01", "2026-06-01", "2026-06-15"],
                    "form": ["4", "4", "4"],
                    "primaryDocument": ["a.xml", "b.xml", "c.xml"],
                }
            }
        }
        result = extract_form4_filings(submissions, since=date(2026, 6, 1))
        assert len(result) == 2
        assert result[0]["filing_date"] == "2026-06-01"
        assert result[1]["filing_date"] == "2026-06-15"

    def test_handles_empty_filings(self) -> None:
        submissions: dict[str, object] = {"filings": {"recent": {}}}
        result = extract_form4_filings(submissions)
        assert result == ()

    def test_handles_missing_filings_key(self) -> None:
        submissions: dict[str, object] = {}
        result = extract_form4_filings(submissions)
        assert result == ()


class TestParseForm4Xml:
    SAMPLE_XML = """<?xml version="1.0"?>
<ownershipDocument>
    <documentType>4</documentType>
    <periodOfReport>2026-06-15</periodOfReport>
    <issuer>
        <issuerCik>0000320193</issuerCik>
        <issuerName>Apple Inc.</issuerName>
        <issuerTradingSymbol>AAPL</issuerTradingSymbol>
    </issuer>
    <reportingOwner>
        <reportingOwnerId>
            <rptOwnerCik>0001780525</rptOwnerCik>
            <rptOwnerName>Newstead Jennifer</rptOwnerName>
        </reportingOwnerId>
        <reportingOwnerRelationship>
            <isOfficer>true</isOfficer>
            <officerTitle>SVP, GC and Secretary</officerTitle>
        </reportingOwnerRelationship>
    </reportingOwner>
    <nonDerivativeTable>
        <nonDerivativeTransaction>
            <securityTitle><value>Common Stock</value></securityTitle>
            <transactionDate><value>2026-06-15</value></transactionDate>
            <transactionCoding>
                <transactionCode>M</transactionCode>
            </transactionCoding>
            <transactionAmounts>
                <transactionShares><value>30104</value></transactionShares>
                <transactionPricePerShare><value>296.42</value></transactionPricePerShare>
                <transactionAcquiredDisposedCode><value>A</value></transactionAcquiredDisposedCode>
            </transactionAmounts>
            <postTransactionAmounts>
                <sharesOwnedFollowingTransaction><value>57784</value></sharesOwnedFollowingTransaction>
            </postTransactionAmounts>
        </nonDerivativeTransaction>
    </nonDerivativeTable>
</ownershipDocument>"""

    def test_parses_issuer_info(self) -> None:
        result = parse_form4_xml(self.SAMPLE_XML)
        assert result is not None
        issuer = result["issuer"]
        assert isinstance(issuer, dict)
        assert issuer["cik"] == "0000320193"
        assert issuer["name"] == "Apple Inc."
        assert issuer["ticker"] == "AAPL"

    def test_parses_owner_info(self) -> None:
        result = parse_form4_xml(self.SAMPLE_XML)
        assert result is not None
        owner = result["owner"]
        assert isinstance(owner, dict)
        assert owner["cik"] == "0001780525"
        assert owner["name"] == "Newstead Jennifer"
        assert owner["is_officer"] is True
        assert owner["officer_title"] == "SVP, GC and Secretary"

    def test_parses_transaction(self) -> None:
        result = parse_form4_xml(self.SAMPLE_XML)
        assert result is not None
        transactions = result["transactions"]
        assert isinstance(transactions, list)
        assert len(transactions) == 1

        txn = transactions[0]
        assert txn["security_title"] == "Common Stock"
        assert txn["transaction_date"] == "2026-06-15"
        assert txn["transaction_code"] == "M"
        assert txn["transaction_type"] == "exercise_conversion"
        assert txn["shares"] == "30104"
        assert txn["price_per_share"] == "296.42"
        assert txn["acquired_disposed"] == "acquired"
        assert txn["shares_after"] == "57784"
        assert txn["is_derivative"] is False

    def test_returns_none_for_malformed_xml(self) -> None:
        result = parse_form4_xml("<not valid xml")
        assert result is None

    def test_parses_period_of_report(self) -> None:
        result = parse_form4_xml(self.SAMPLE_XML)
        assert result is not None
        assert result["period_of_report"] == "2026-06-15"


class TestParseFullTextSearchResponse:
    def test_parses_search_hits(self) -> None:
        data = {
            "took": 100,
            "hits": {
                "total": {"value": 1000},
                "hits": [
                    {
                        "_score": 8.5,
                        "_source": {
                            "ciks": ["0000320193"],
                            "display_names": ["Apple Inc.  (AAPL)"],
                            "form": "10-K",
                            "file_date": "2026-03-01",
                            "adsh": "0001234567-26-000123",
                            "file_type": "10-K",
                            "file_description": "Annual Report",
                        },
                    }
                ],
            },
        }
        result = parse_full_text_search_response(data)
        assert len(result) == 1
        assert result[0]["score"] == 8.5
        assert result[0]["ciks"] == ["0000320193"]
        assert result[0]["form"] == "10-K"
        assert result[0]["accession_number"] == "0001234567-26-000123"

    def test_handles_empty_hits(self) -> None:
        data: dict[str, object] = {"hits": {"hits": []}}
        result = parse_full_text_search_response(data)
        assert result == ()

    def test_handles_missing_hits(self) -> None:
        data: dict[str, object] = {}
        result = parse_full_text_search_response(data)
        assert result == ()
