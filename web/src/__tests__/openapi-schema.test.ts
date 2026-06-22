import openapi from "../../openapi.json";
import type { AccountSnapshot } from "@/api/client";

describe("generated OpenAPI schema", () => {
  it("contains the portfolio response model used by the dashboard", () => {
    expect(openapi.components.schemas.AccountSnapshot).toBeDefined();
    expect(openapi.components.schemas.PositionSnapshot).toBeDefined();

    const sample = {
      accountId: "paper-001",
      cash: "200000",
      cashCurrency: "USD",
      marketValue: "77500",
      netLiquidation: "277500",
      buyingPower: "277500",
      asOf: null,
      positions: [],
    } satisfies AccountSnapshot;

    expect(sample.accountId).toBe("paper-001");
  });
});
