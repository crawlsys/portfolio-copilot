import React from "react";
import { render, screen } from "@testing-library/react";
import { DisclosureCard } from "@/components/disclosure-feed/DisclosureCard";
import type { CongressionalDisclosure } from "@/api/client";

const disclosure: CongressionalDisclosure = {
  filingId: "seed-001-P000197-NVDA",
  memberId: "P000197",
  memberName: "Nancy Pelosi",
  member: {
    memberId: "P000197",
    name: "Nancy Pelosi",
    chamber: "house",
    party: "Democratic",
    state: "CA",
    district: "11",
    committees: ["Appropriations"],
  },
  symbol: "NVDA",
  assetClass: "EQUITY",
  assetDescription: "NVIDIA Corporation",
  transactionType: "BUY",
  transactionDate: "2026-05-22T00:00:00Z",
  disclosureDate: "2026-06-06T00:00:00Z",
  amountRangeLow: 500001,
  amountRangeHigh: 1000000,
  lagDays: 15,
};

describe("DisclosureCard", () => {
  it("renders member, ticker, transaction, amount, and lag", () => {
    render(<DisclosureCard disclosure={disclosure} />);

    expect(screen.getByText("Nancy Pelosi")).toBeInTheDocument();
    expect(screen.getByText("NVDA")).toBeInTheDocument();
    expect(screen.getByText("BUY")).toBeInTheDocument();
    expect(screen.getByText("$500,001 - $1,000,000")).toBeInTheDocument();
    expect(screen.getByText("15 days")).toBeInTheDocument();
  });
});
