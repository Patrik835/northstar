import { expect, test } from "@playwright/test";

for (const broker of ["binance", "bybit"]) {
  test(`${broker} P/L stays unavailable without purchase history`, async ({ page }) => {
    await page.route("**/api/v1/auth/me", (route) => route.fulfill({ json: {
      id: "test-user", username: "crypto-test", is_admin: false,
    } }));
    await page.route("**/api/v1/activity?**", (route) => route.fulfill({ json: { items: [] } }));
    await page.route("**/api/v1/holdings", (route) => {
      const performance = {
        cost_basis_eur: null, open_pnl_eur: null,
        open_pnl_percentage: null,
        open_pnl_source: "unavailable",
        realized_pnl_eur: null, income_eur: "0", fees_eur: "0", total_return_eur: null,
        coverage: "unavailable", missing_event_count: 0,
      };
      const source = {
        broker, connection_id: "exchange-id", provider_instrument_id: "ETH",
        provider_symbol: "ETH", provider_name: "Ethereum", note: null,
        canonical_instrument_id: "eth-id", canonical_symbol: "ETH", canonical_name: "Ethereum",
        canonical_isin: null, quantity: "2", average_price: null,
        current_value: "400", current_value_eur: "400", currency: "EUR",
        reported_pnl: null, reported_pnl_eur: null, instrument_percentage: "100",
        last_synced_at: null, valued_at: null, valuation_source: "market",
        is_estimated: false, freshness_status: "fresh", is_stale: false,
        calculated_cost_eur: null, calculated_gain_eur: null,
        calculated_gain_percentage: null,
        gain_coverage: "unavailable", performance,
      };
      return route.fulfill({ json: {
        currency: "EUR", total_value_eur: "400", reported_pnl_eur: null,
        position_count: 1, instrument_count: 1, unmatched_positions: 0,
        as_of: null, stale_source_count: 0, estimated_position_count: 0,
        reconciliation_warnings: [], sources: [{ label: broker, value_eur: "400", percentage: "100" }],
        performance, holdings: [{
          key: "eth", grouping: "instrument", instrument_count: 1,
          canonical_instrument_id: "eth-id", symbol: "ETH", symbols: ["ETH"], name: "Ethereum",
          isin: null, asset_type: "crypto", total_quantity: "2", total_value_eur: "400",
          reported_pnl_eur: null, reported_pnl_source_count: 0, portfolio_percentage: "100",
          source_count: 1, as_of: null, is_stale: false, stale_source_count: 0,
          has_estimated_value: false, sources: [source], calculated_cost_eur: null,
          calculated_gain_eur: null, calculated_gain_percentage: null, gain_coverage: "unavailable",
          performance, category: null, tags: [], notes: null, target_allocation_percentage: null,
        }],
      } });
    });
    await page.goto("/holdings");
    await page.locator(".holding-row").click();
    await expect(page.getByText("Enter purchase price for P/L", { exact: true })).toHaveCount(0);
    await expect(page.getByLabel("Average purchase price per unit", { exact: true })).toHaveCount(0);
    await expect(page.locator(".source-detail")).toHaveCount(1);
    await expect(page.locator(".source-detail")).toContainText("Not available");
    await expect(page.locator(".holding-row")).not.toContainText("Open P/L +");
  });
}
