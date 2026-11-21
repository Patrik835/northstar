import { expect, test } from "@playwright/test";

const guide = (broker: string, displayName: string, endpoint: string) => ({
  broker, display_name: displayName, short_mark: displayName.slice(0, 2),
  connection_type: "csv", category: "Broker", description: `${displayName} statements`,
  credential_fields: [], credential_labels: {}, security_notice: "", setup_steps: [],
  tutorial_url: "https://example.com", sync_frequency_label: null,
  file_import: {
    endpoint, accept: ".csv,text/csv", multiple: false, prompt: "Select CSV",
    help_text: "CSV", empty_file_message: "Choose a file", holding_label: "holding",
  },
});

test("recognises a statement's broker and imports only after confirming", async ({ page }) => {
  let imported = "";
  await page.route("**/api/v1/auth/me", (route) => route.fulfill({ json: {
    id: "test-user", username: "detect-test", is_admin: false,
  } }));
  await page.route("**/api/v1/dashboard/features", (route) => route.fulfill({ json: {
    ai: false, news: false, benchmarks: false,
  } }));
  await page.route("**/api/v1/connections", (route) => route.fulfill({ json: [] }));
  await page.route("**/api/v1/connections/guides", (route) => route.fulfill({ json: [
    guide("trade_republic", "Trade Republic", "/connections/imports/trade-republic"),
    guide("scalable_capital", "Scalable Capital", "/connections/imports/scalable-capital"),
  ] }));
  await page.route("**/api/v1/connections/imports/detect", (route) => route.fulfill({ json: {
    suggested: "trade_republic",
    matches: [
      { broker: "trade_republic", display_name: "Trade Republic", score: 1 },
      { broker: "scalable_capital", display_name: "Scalable Capital", score: 1 },
    ],
  } }));
  await page.route("**/api/v1/connections/imports/*", (route) => {
    const url = route.request().url();
    if (url.endsWith("/detect")) return route.fallback();
    imported = url.split("/").pop() ?? "";
    return route.fulfill({ json: {
      connection: {}, rows_read: 2, transactions_added: 2, duplicates_skipped: 0,
      positions_imported: 1, warnings: [],
    } });
  });

  await page.goto("/connections?type=csv");
  await page.locator(".statement-detector input[type=file]").setInputFiles({
    name: "export.csv", mimeType: "text/csv", buffer: Buffer.from("account_type,type\n"),
  });

  await expect(page.getByText("This looks like a")).toContainText("Trade Republic");
  expect(imported).toBe("");
  await expect(page.getByRole("button", { name: "Scalable Capital" })).toBeVisible();

  await page.getByRole("button", { name: "Import as Trade Republic" }).click();
  await expect(page.getByText("Trade Republic: imported 1 holding and 2 new transactions."))
    .toBeVisible();
  expect(imported).toBe("trade-republic");
});
