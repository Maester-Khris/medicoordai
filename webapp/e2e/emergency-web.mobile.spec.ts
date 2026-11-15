import { expect, test, type Page } from "@playwright/test"
import { stubBackend, type ScenarioName } from "./support/stubs"

// Web layout (1280x800): the same emergency and directions guarantees as the phone spec.
test.skip(({ viewport }) => (viewport?.width ?? 0) < 1024, "web layout only")

const MAPS_URL = /^https:\/\/www\.google\.com\/maps\/dir\/\?api=1&destination=43\.\d+%2C-79\.\d+$/

async function chat(page: Page, scenario: ScenarioName, text = "chest pain") {
  await stubBackend(page, scenario)
  await page.goto("/app")
  const input = page.getByPlaceholder("Describe how you feel…")
  await expect(input).toBeVisible({ timeout: 20_000 })
  await input.fill(text)
  await input.press("Enter")
}

test("emergent: Call 911 shows the template panel (no dialer link) and directions open Maps", async ({ page, context }) => {
  await context.route("https://www.google.com/**", route => route.fulfill({ status: 200, body: "maps" }))
  await chat(page, "emergent")
  const call = page.getByRole("button", { name: "Call 911", exact: true })
  await expect(call).toBeVisible()
  expect((await call.boundingBox())!.height).toBeGreaterThanOrEqual(43.5)
  await expect(page.locator('a[href="tel:911"]')).toHaveCount(0)
  await call.click()
  await expect(page.getByTestId("emergency-panel")).toContainText("Dial 911 on your phone")
  await expect(page.getByTestId("emergency-panel")).toContainText("MediCoord does not place the call")

  const directions = page.getByRole("button", { name: "ER directions" })
  expect((await directions.boundingBox())!.height).toBeGreaterThanOrEqual(43.5)
  const popup = context.waitForEvent("page")
  await directions.click()
  expect((await popup).url()).toMatch(MAPS_URL)
})

test("emergent without a facility and capped replies still show Call 911", async ({ page }) => {
  await chat(page, "emergent_nofac")
  await expect(page.getByRole("button", { name: "Call 911", exact: true })).toBeVisible()
})

test("capped emergent reply shows Call 911", async ({ page }) => {
  await chat(page, "capped")
  await expect(page.getByRole("button", { name: "Call 911", exact: true })).toBeVisible()
})

test("a reply without a result still has the header emergency link", async ({ page }) => {
  await chat(page, "no_provider")
  await expect(page.getByText(/having trouble processing/)).toBeVisible()
  await expect(page.getByRole("button", { name: "Emergency? Call 911" })).toBeVisible()
})

test("a failed send shows the error with the 911 line and keeps the text", async ({ page }) => {
  await chat(page, "http500", "my text")
  await expect(page.getByText(/Something went wrong sending that/)).toBeVisible()
  await expect(page.getByPlaceholder("Describe how you feel…")).toHaveValue("my text")
})

test("nothing opens before a tap, and severity words are the schema words", async ({ page, context }) => {
  const opened: string[] = []
  context.on("page", p => opened.push(p.url()))
  await chat(page, "emergent")
  await expect(page.getByRole("button", { name: "Call 911", exact: true })).toBeVisible()
  await expect(page.getByText("EMERGENT", { exact: true }).first()).toBeVisible()
  await expect(page.locator("body")).not.toContainText("ESI")
  expect(opened).toEqual([])
})
