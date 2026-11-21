import { expect, test } from "@playwright/test";

test("selects an asset and saves only purchase details and an optional note", async ({ page }) => {
  await page.route("**/api/v1/auth/me", (route) => route.fulfill({ json: {
    id: "test-user", username: "manual-test", is_admin: false,
  } }));
  await page.route("**/api/v1/holdings", (route) => route.fulfill({ json: {
    currency: "EUR", total_value_eur: "0", reported_pnl_eur: null,
    position_count: 0, instrument_count: 0, unmatched_positions: 0,
    as_of: null, stale_source_count: 0, estimated_position_count: 0,
    reconciliation_warnings: [], sources: [], holdings: [],
  } }));
  let saved: Record<string, unknown> | null = null;
  await page.route("**/api/v1/holdings/manual", async (route) => {
    saved = route.request().postDataJSON();
    await route.fulfill({ status: 201, json: { id: "manual-id" } });
  });
  await page.goto("/holdings");
  await page.getByRole("button", { name: "Add holding" }).click();
  const form = page.locator(".manual-position-modal");
  await expect(form.getByRole("button", { name: "Add holding", exact: true })).toBeDisabled();
  await expect(form.getByText("3,000 stocks · 150 cryptocurrencies · Search by name or ticker")).toBeVisible();
  const search = form.getByRole("combobox", { name: "Asset", exact: true });
  await search.fill("btc");
  await expect(form.getByRole("listbox").getByRole("option").first()).toContainText("Bitcoin");
  await search.press("Enter");
  await expect(form.getByLabel("Purchase price per unit", { exact: true })).toBeFocused();
  await expect(form.locator(".asset-selected")).toContainText("Bitcoin");
  const bounds = await form.boundingBox();
  expect(bounds).not.toBeNull();
  expect(bounds!.x).toBeGreaterThanOrEqual(0);
  expect(bounds!.x + bounds!.width).toBeLessThanOrEqual(page.viewportSize()!.width);
  expect(await form.evaluate((element) => element.scrollWidth <= element.clientWidth)).toBe(true);
  await expect(search).toHaveCount(0);
  await form.getByRole("button", { name: "Change", exact: true }).click();
  await form.getByRole("combobox", { name: "Asset", exact: true }).fill("bitcoin");
  await form.getByRole("option", { name: "BTC Bitcoin CRYPTO", exact: true }).click();
  await form.getByLabel("Purchase price per unit", { exact: true }).fill("50000");
  await form.getByLabel("Quantity", { exact: true }).fill("0.5");
  await form.getByLabel("Note optional", { exact: true }).fill("Hardware wallet");
  await expect(form.locator('input[name="name"], input[name="current_price"], input[name="isin"]')).toHaveCount(0);
  await expect(form.locator('input, textarea')).toHaveCount(3);
  await form.getByRole("button", { name: "Add holding", exact: true }).click();
  await expect(page.getByText("Holding added.", { exact: true })).toBeVisible();
  expect(saved).toEqual({
    ticker: "BTC", name: "Bitcoin", asset_type: "crypto", quantity: "0.5",
    average_price: "50000", current_price: null, currency: "EUR",
    isin: null, note: "Hardware wallet",
  });
});

test("searches the complete catalogue including its lowest-ranked entries", async ({ page, request }) => {
  const response = await request.get("/asset-catalogue.json");
  expect(response.ok()).toBe(true);
  const catalogue = await response.json() as {
    assets: Array<{ ticker: string; name: string; asset_type: string; rank: number }>;
  };
  expect(catalogue.assets.filter((asset) => asset.asset_type === "stock")).toHaveLength(3000);
  expect(catalogue.assets.filter((asset) => asset.asset_type === "crypto")).toHaveLength(150);
  await page.route("**/api/v1/auth/me", (route) => route.fulfill({ json: {
    id: "test-user", username: "manual-test", is_admin: false,
  } }));
  await page.route("**/api/v1/holdings", (route) => route.fulfill({ json: {
    currency: "EUR", total_value_eur: "0", reported_pnl_eur: null,
    position_count: 0, instrument_count: 0, unmatched_positions: 0,
    as_of: null, stale_source_count: 0, estimated_position_count: 0,
    reconciliation_warnings: [], sources: [], holdings: [],
  } }));
  await page.goto("/holdings");
  await page.getByRole("button", { name: "Add holding" }).click();
  const form = page.locator(".manual-position-modal");
  await expect(form.getByText("3,000 stocks · 150 cryptocurrencies · Search by name or ticker")).toBeVisible();
  for (const type of ["stock", "crypto"]) {
    const asset = catalogue.assets.filter((item) => item.asset_type === type).at(-1)!;
    await form.getByRole("combobox", { name: "Asset", exact: true }).fill(asset.ticker);
    const option = form.getByRole("listbox").getByRole("option").filter({ hasText: asset.name }).first();
    await expect(option).toBeVisible();
    await option.click();
    await expect(form.locator(".asset-selected")).toContainText(asset.name);
    await form.getByRole("button", { name: "Change", exact: true }).click();
  }
});
