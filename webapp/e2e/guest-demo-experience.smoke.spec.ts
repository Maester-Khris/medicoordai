import { expect, test, type Page } from "@playwright/test"

// Deployed checks for sprint 21: travel modes routed by the backend, the distance filter, and no
// sandbox link for guests. Runs with playwright.smoke.config.ts (SMOKE_BASE_URL, desktop viewport,
// geolocation granted at the University of Toronto).
const FOLLOW_UP_ANSWER =
  "It started an hour ago, the pain is strong and constant, I am 45 with no other conditions. Please recommend where to go."

async function openApp(page: Page): Promise<void> {
  await page.goto("/")
  // "Go to App" only renders once /config has resolved and the guest exists.
  await expect(page.getByRole("button", { name: "Go to App" })).toBeVisible()
  await page.getByRole("button", { name: "Get started" }).first().click()
  await expect(page).toHaveURL(/\/app$/)
}

/** Starts a conversation and answers follow-ups until a recommendation is on screen. */
async function reachRecommendation(page: Page): Promise<void> {
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
}

test("a mode change is routed by the backend and redraws the route", async ({ page }) => {
  const geoapifyCalls: string[] = []
  page.on("request", request => {
    if (request.url().includes("api.geoapify.com")) geoapifyCalls.push(request.url())
  })

  const firstRoutes = page.waitForResponse(
    res => res.url().endsWith("/routes") && res.request().method() === "POST",
    { timeout: 110_000 },
  )
  await openApp(page)
  await reachRecommendation(page)

  const carResponse = await firstRoutes
  expect(carResponse.status()).toBe(200)
  expect(carResponse.request().postDataJSON().mode).toBe("car")
  await expect(page.locator(".leaflet-overlay-pane path").first()).toBeVisible()

  const bikeRoutes = page.waitForResponse(
    res => res.url().endsWith("/routes") && res.request().postDataJSON()?.mode === "bike",
  )
  const modeChanged = page.waitForResponse(
    res => res.url().endsWith("/events") && res.request().postDataJSON()?.type === "mode_changed",
  )
  await page.getByTestId("mode-bike").click()

  const bikeResponse = await bikeRoutes
  expect(bikeResponse.status()).toBe(200)
  const body = await bikeResponse.json()
  expect(body.mode).toBe("bike")
  expect(body.fastest_facility_id).not.toBeNull()

  const event = await modeChanged
  expect(event.status()).toBe(204)
  const sent = event.request().postDataJSON()
  expect(sent.mode).toBe("bike")
  expect(sent.duration_ms).toBeGreaterThanOrEqual(0)

  await expect(page.getByTestId("mode-bike")).toHaveAttribute("aria-pressed", "true")
  await expect(page.locator(".leaflet-overlay-pane path").first()).toBeVisible()
  expect(geoapifyCalls).toEqual([])
})

test("a category chip plus a radius filters the map through the nearby endpoint", async ({ page }) => {
  await openApp(page)

  const markers = page.locator(".leaflet-marker-pane .leaflet-marker-icon")
  await expect.poll(async () => markers.count(), { timeout: 30_000 }).toBeGreaterThan(20)
  const before = await markers.count()

  await page.getByRole("button", { name: /^Hospital \(\d+\)$/ }).click()

  const nearby = page.waitForResponse(res => res.url().includes("/facilities/nearby"))
  await page.getByTestId("proximity-toggle").click()
  await page.getByRole("button", { name: "10 km", exact: true }).click()

  const response = await nearby
  expect(response.status()).toBe(200)
  expect(new URL(response.url()).searchParams.get("category")).toBe("hospital")
  const rows = (await response.json()) as { facility_id: string; distance_m: number }[]
  expect(rows.length).toBeGreaterThan(0)
  expect(Math.max(...rows.map(r => r.distance_m))).toBeLessThanOrEqual(10_000)

  // Facility markers now come from the nearby rows; the user and landmark markers add at most three.
  await expect.poll(async () => markers.count(), { timeout: 15_000 }).toBeLessThanOrEqual(rows.length + 3)
  expect(await markers.count()).toBeLessThan(before)
})

test("a guest sees no sandbox link and cannot open the sandbox", async ({ page }) => {
  await page.goto("/")
  await expect(page.getByRole("button", { name: "Go to App" })).toBeVisible()
  await expect(page.locator('a[href="/sandbox"]')).toHaveCount(0)

  await page.goto("/for-investors")
  await expect(page.getByRole("heading", { name: "See the coordination in action" })).toBeVisible()
  await expect(page.locator('a[href="/sandbox"]')).toHaveCount(0)

  await page.goto("/sandbox")
  await expect(page).toHaveURL(/\/app$/)
})
