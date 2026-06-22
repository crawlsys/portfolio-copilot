import React from "react";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { PositionsTable } from "@/components/PositionsTable";
import type { PositionSnapshot } from "@/api/client";

const positions: PositionSnapshot[] = [
  {
    symbol: "META",
    assetClass: "EQUITY",
    quantity: "350.0000",
    averageCost: "359.9327",
    marketValue: "221378.50",
    unrealizedPnl: "95402.06",
  },
  {
    symbol: "AAPL",
    assetClass: "EQUITY",
    quantity: "100.0000",
    averageCost: "150.00",
    marketValue: "17500.00",
    unrealizedPnl: "2500.00",
  },
];

describe("PositionsTable", () => {
  it("renders positions and filters by symbol", async () => {
    const user = userEvent.setup();
    render(<PositionsTable positions={positions} />);

    expect(screen.getByText("META")).toBeInTheDocument();
    expect(screen.getByText("AAPL")).toBeInTheDocument();

    await user.type(screen.getByPlaceholderText("Filter symbols"), "meta");

    expect(screen.getByText("META")).toBeInTheDocument();
    expect(screen.queryByText("AAPL")).not.toBeInTheDocument();
  });
});
