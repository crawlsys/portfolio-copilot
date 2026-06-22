import React from "react";
import { render, screen } from "@testing-library/react";
import { AccountKpiCard } from "@/components/AccountKpiCard";

describe("AccountKpiCard", () => {
  it("renders the KPI label and value", () => {
    render(<AccountKpiCard label="Net Liquidation" value="$1,600,000" />);

    expect(screen.getByText("Net Liquidation")).toBeInTheDocument();
    expect(screen.getByText("$1,600,000")).toBeInTheDocument();
  });
});
