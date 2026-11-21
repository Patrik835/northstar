import { expect, test } from "@playwright/test";

const broker = "binance";
test("platform filter scopes all performance figures", async ({ page }) => {
    await page.route("**/api/v1/auth/me", (route) => route.fulfill({ json: {
      id: "test-user", username: "crypto-test", is_admin: false,
    } }));
    await page.route("**/api/v1/activity?**", (route) => route.fulfill({ json: { items: [] } }));
    await page.route("**/api/v1/holdings", (route) => {
      const performance = {
        cost_basis_eur: "100", open_pnl_eur: "50", open_pnl_percentage: "50",
        open_pnl_source: "calculated", realized_pnl_eur: "10", income_eur: "3",
        fees_eur: "1", total_return_eur: "62", coverage: "complete", missing_event_count: 0,
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
      const other = { ...source, broker: "bybit", connection_id: "other-exchange",
        current_value_eur: "280", performance: { ...performance, cost_basis_eur: "200",
        open_pnl_eur: "80", realized_pnl_eur: "20", income_eur: "7", fees_eur: "2", total_return_eur: "105" } };
      const combined = { ...performance, cost_basis_eur: "300", open_pnl_eur: "130",
        realized_pnl_eur: "30", income_eur: "10", fees_eur: "3", total_return_eur: "167" };
      return route.fulfill({ json: {
        currency: "EUR", total_value_eur: "400", reported_pnl_eur: null,
        position_count: 1, instrument_count: 1, unmatched_positions: 0,
        as_of: null, stale_source_count: 0, estimated_position_count: 0,
        reconciliation_warnings: [], sources: [{ label: broker, value_eur: "400", percentage: "50" }, { label: "bybit", value_eur: "280", percentage: "50" }],
        performance, holdings: [{
          key: "eth", grouping: "instrument", instrument_count: 1,
          canonical_instrument_id: "eth-id", symbol: "ETH", symbols: ["ETH"], name: "Ethereum",
          isin: null, asset_type: "crypto", total_quantity: "2", total_value_eur: "400",
          reported_pnl_eur: null, reported_pnl_source_count: 0, portfolio_percentage: "100",
          source_count: 1, as_of: null, is_stale: false, stale_source_count: 0,
          has_estimated_value: false, sources: [source, other], calculated_cost_eur: null,
          calculated_gain_eur: null, calculated_gain_percentage: null, gain_coverage: "unavailable",
          performance: combined, category: null, tags: [], notes: null, target_allocation_percentage: null,
        }],
      } });
    });
    await page.goto("/holdings");
    await page.locator(".holding-row").click();
    const strip = page.locator(".holding-performance-strip");
    await expect(strip).toContainText("+€167");
    await page.getByLabel("Broker").selectOption(broker);
    await expect(strip).toContainText("+€62.00");
    await expect(strip).toContainText("+€10.00");
    await expect(strip).toContainText("€3.00");
    await expect(strip).toContainText("−€1.00");
    await expect(strip).not.toContainText("+€167");
    await expect(page.locator(".cost-basis-inline")).toContainText("€100");
    await expect(page.locator(".source-detail")).toHaveCount(1);
  });
