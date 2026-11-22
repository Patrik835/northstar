import { expect, test } from "@playwright/test";

test.use({ colorScheme: "light" });

test("theme follows the device until the user switches, then remembers the choice", async ({ page }) => {
  await page.route("**/api/v1/**", (route) => {
    const path = new URL(route.request().url()).pathname;
    if (path.endsWith("/auth/me")) {
      return route.fulfill({ json: { id: "u", username: "theme-test", is_admin: false } });
    }
    if (path.endsWith("/dashboard/features")) {
      return route.fulfill({ json: { ai: false, news: false, benchmarks: false } });
    }
    return route.fulfill({ json: [] });
  });

  await page.goto("/connections");
  const html = page.locator("html");
  await expect(html).toHaveAttribute("data-theme", "light");

  await page.getByRole("button", { name: "Switch to dark theme" }).click();
  await expect(html).toHaveAttribute("data-theme", "dark");

  await page.reload();
  await expect(html).toHaveAttribute("data-theme", "dark");
  await expect(page.getByRole("button", { name: "Switch to light theme" })).toBeVisible();
});
