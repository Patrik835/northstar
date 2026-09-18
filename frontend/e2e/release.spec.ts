import AxeBuilder from "@axe-core/playwright";
import { expect, test, type APIRequestContext, type Page } from "@playwright/test";

const mailpitUrl = process.env.E2E_MAILPIT_URL ?? "http://127.0.0.1:8025";

type MailSummary = { ID: string; Subject: string; To?: Array<{ Address?: string }> };

async function expectNoSeriousAccessibilityViolations(page: Page) {
  const results = await new AxeBuilder({ page }).analyze();
  expect(
    results.violations.filter((item) => ["serious", "critical"].includes(item.impact ?? "")),
  ).toEqual([]);
}

async function emailLink(
  request: APIRequestContext,
  recipient: string,
  subject: string,
): Promise<string> {
  for (let attempt = 0; attempt < 30; attempt += 1) {
    const response = await request.get(`${mailpitUrl}/api/v1/messages`);
    const payload = await response.json() as { messages?: MailSummary[] };
    const message = payload.messages?.find((item) =>
      item.Subject === subject && item.To?.some((address) => address.Address === recipient)
    );
    if (message) {
      const detail = await request.get(`${mailpitUrl}/api/v1/message/${message.ID}`);
      const body = await detail.json() as { Text?: string; HTML?: string };
      const match = `${body.Text ?? ""}\n${body.HTML ?? ""}`.match(
        /https?:\/\/[^\s<>"']+(?:verify-email|reset-password)[^\s<>"']*/,
      );
      if (match) return match[0].replaceAll("&amp;", "&");
    }
    await new Promise((resolve) => setTimeout(resolve, 500));
  }
  throw new Error(`No ${subject} email arrived for ${recipient}`);
}

test.describe.serial("public release account lifecycle", () => {
  const originalPassword = "Release-ready-password-1";
  const resetPassword = "Release-ready-password-2";

  test("registers, verifies, signs in, exports, resets, and deletes an account", async ({
    page,
    request,
  }, testInfo) => {
    const suffix = `${Date.now()}_${testInfo.project.name.replaceAll(/\W/g, "_")}`;
    const username = `release_${suffix}`;
    const email = `release_${suffix}@example.test`;
    await page.goto("/register");
    await page.getByLabel("Username").fill(username);
    await page.getByLabel("Email", { exact: true }).fill(email);
    await page.getByLabel("Password", { exact: true }).fill(originalPassword);
    await page.getByLabel("Confirm password").fill(originalPassword);
    await page.getByRole("button", { name: "Create account" }).click();
    await expect(page.getByRole("heading", { name: "Check your email" })).toBeVisible();

    await page.goto(await emailLink(request, email, "Verify your Northstar account"));
    await expect(page.getByRole("heading", { name: "You’re verified" })).toBeVisible();
    await page.getByRole("link", { name: "Continue to sign in" }).click();
    await page.getByLabel("Username").fill(username);
    await page.getByLabel("Password").fill(originalPassword);
    await page.getByRole("button", { name: "Sign in" }).click();
    await expect(page.getByRole("heading", { name: "Your financial picture" })).toBeVisible();
    await expectNoSeriousAccessibilityViolations(page);

    await page.getByRole("link", { name: "Settings" }).click();
    await expectNoSeriousAccessibilityViolations(page);
    const dataPanel = page.locator(".data-controls");
    await dataPanel.getByLabel("Current password").fill(originalPassword);
    const downloadPromise = page.waitForEvent("download");
    await dataPanel.getByRole("button", { name: "Download my data" }).click();
    const download = await downloadPromise;
    expect(download.suggestedFilename()).toMatch(/^northstar-account-.*\.json$/);

    await page.getByRole("button", { name: "Sign out" }).click();
    await page.getByRole("link", { name: "Forgot your password?" }).click();
    await page.getByLabel("Email address").fill(email);
    await page.getByRole("button", { name: "Send reset link" }).click();
    await expect(page.getByRole("status")).toContainText("If an account exists");
    await page.goto(await emailLink(request, email, "Reset your Northstar password"));
    await page.getByLabel("New password").fill(resetPassword);
    await page.getByLabel("Confirm password").fill(resetPassword);
    await page.getByRole("button", { name: "Reset password" }).click();
    await expect(page.getByRole("status")).toContainText("Password reset");

    await page.getByRole("link", { name: "Back to sign in" }).click();
    await page.getByLabel("Username").fill(username);
    await page.getByLabel("Password").fill(resetPassword);
    await page.getByRole("button", { name: "Sign in" }).click();
    await page.getByRole("link", { name: "Settings" }).click();
    await page.getByText("Delete account", { exact: true }).click();
    const dangerZone = page.locator(".danger-zone");
    await dangerZone.getByLabel("Current password").fill(resetPassword);
    await dangerZone.getByLabel("Type DELETE to confirm").fill("DELETE");
    page.on("dialog", (dialog) => dialog.accept());
    await dangerZone.getByRole("button", { name: "Delete permanently" }).click();
    await expect(page.getByRole("heading", { name: "Sign in" })).toBeVisible();
  });

  test("login and recovery pages have no serious accessibility violations", async ({ page }) => {
    for (const path of ["/login", "/register", "/forgot-password"]) {
      await page.goto(path);
      await expectNoSeriousAccessibilityViolations(page);
    }
  });
});
