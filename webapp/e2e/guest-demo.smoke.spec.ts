import { expect, test } from "@playwright/test"

// The one path the demo is measured on: land → starter → recommendation → route drawn → feedback.
// The LLM may ask a follow-up before recommending, so the test answers up to three times.
const FOLLOW_UP_ANSWER =
  "It started an hour ago, the pain is strong and constant, I am 45 with no other conditions. Please recommend where to go."

test("guest reaches a drawn route and leaves feedback", async ({ page }) => {
  const routeDrawn = page.waitForResponse(
    res => res.url().endsWith("/events") && res.request().method() === "POST",
    { timeout: 110_000 },
  )

  await page.goto("/")
  // "Go to App" only renders once /config has resolved and the guest exists; before that the
  // "Get started" button would open the sign-up modal instead of navigating.
  await expect(page.getByRole("button", { name: "Go to App" })).toBeVisible()
  await expect(page.getByRole("button", { name: "Sign in" })).toHaveCount(0)
  await page.getByRole("button", { name: "Get started" }).first().click()
  await expect(page).toHaveURL(/\/app$/)

  await expect(page.getByTestId("medical-notice")).toBeVisible()
  await expect(page.getByRole("button", { name: "Sign in" })).toHaveCount(0)

  await page.getByTestId("starter-prompt").nth(1).click() // "Chest pain and shortness of breath"

  const feedback = page.getByTestId("feedback-control")
  const input = page.getByPlaceholder("Describe how you feel…")
  for (let attempt = 0; attempt < 3; attempt++) {
    try {
      await feedback.waitFor({ state: "visible", timeout: 30_000 })
      break
    } catch {
      await expect(page.getByTestId("busy-banner")).toHaveCount(0)
      await input.fill(FOLLOW_UP_ANSWER)
      await input.press("Enter")
    }
  }
  await expect(feedback).toBeVisible()

  expect((await routeDrawn).status()).toBe(204)
  await expect(page.locator(".leaflet-overlay-pane path").first()).toBeVisible()

  const saved = page.waitForResponse(
    res => res.url().endsWith("/feedback") && res.request().method() === "POST",
  )
  await page.getByTestId("feedback-up").click()
  expect((await saved).status()).toBe(204)
  await expect(page.getByTestId("feedback-saved")).toBeVisible()
})
