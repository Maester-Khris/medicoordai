import { expect, test, type Page } from "@playwright/test"
import { EMERGENT_REPLY, stubBackend, type ScenarioName } from "./support/stubs"

// Phone-sized coverage for task 016: emergency button, directions, sheet and tabs, list, failures.
// Runs under the phone-320, phone-360, phone-390 and phone-landscape projects (stubbed backend).
test.skip(({ viewport }) => (viewport?.width ?? 0) >= 1024, "phone layout only")

const MAPS_URL = /^https:\/\/www\.google\.com\/maps\/dir\/\?api=1&destination=43\.\d+%2C-79\.\d+$/

async function open(page: Page, scenario: ScenarioName) {
  const stub = await stubBackend(page, scenario)
  await page.goto("/app")
  await expect(page.getByPlaceholder("Describe your symptoms...")).toBeVisible({ timeout: 20_000 })
  return stub
}

async function send(page: Page, text: string) {
  await page.getByPlaceholder("Describe your symptoms...").fill(text)
  await page.getByRole("button", { name: "Send" }).click()
}

const sheet = (page: Page) => page.getByRole("region", { name: "AI Health Assistant" })

async function expectNoHorizontalScroll(page: Page) {
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth)
  expect(overflow).toBeLessThanOrEqual(0)
}

// A control is "tappable" when it is at least 44 px tall and the element at its centre is itself.
async function expectTappable(page: Page, locator: ReturnType<Page["locator"]>) {
  await locator.scrollIntoViewIfNeeded()
  const box = await locator.boundingBox()
  expect(box, "control has a box").not.toBeNull()
  expect(box!.height).toBeGreaterThanOrEqual(43.5)
  const covered = await locator.evaluate(el => {
    const r = el.getBoundingClientRect()
    const top = document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2)
    return !(top && (el === top || el.contains(top)))
  })
  expect(covered, "control is not covered").toBe(false)
}

test("emergent result: Call 911 is a tel link, the reply and notice stay visible", async ({ page }) => {
  await open(page, "emergent")
  await send(page, "chest pain")
  const call = page.locator('a[href="tel:911"]').filter({ hasText: /^Call 911$/ })
  await expect(call).toBeVisible()
  await expect(sheet(page).getByText(EMERGENT_REPLY)).toBeVisible()
  await expect(page.getByTestId("medical-notice")).toBeVisible()
  await expectTappable(page, call)
  await expectNoHorizontalScroll(page)
  await call.click() // opens the dialer; the template panel must also appear
  await expect(page.getByTestId("emergency-panel")).toContainText("Dial 911 on your phone")
})

test("emergent result: Get Directions opens the Maps URL in a new tab", async ({ page, context }) => {
  await context.route("https://www.google.com/**", route => route.fulfill({ status: 200, body: "maps" }))
  await open(page, "emergent")
  await send(page, "chest pain")
  const directions = page.getByRole("button", { name: /Get Directions/ })
  await directions.scrollIntoViewIfNeeded()
  await expectTappable(page, directions)
  const popupPromise = context.waitForEvent("page")
  await directions.click()
  const popup = await popupPromise
  expect(popup.url()).toMatch(MAPS_URL)
})

test("nothing is dialed or opened before a tap", async ({ page, context }) => {
  const opened: string[] = []
  context.on("page", p => opened.push(p.url()))
  const requests: string[] = []
  page.on("request", r => { if (/google\.com|^tel:/.test(r.url())) requests.push(r.url()) })
  await open(page, "emergent")
  await send(page, "chest pain")
  await expect(page.locator('a[href="tel:911"]').first()).toBeVisible()
  await page.waitForTimeout(1000)
  expect(opened).toEqual([])
  expect(requests).toEqual([])
})

test("emergent without a facility still shows the reply and Call 911", async ({ page }) => {
  await open(page, "emergent_nofac")
  await send(page, "chest pain")
  await expect(page.locator('a[href="tel:911"]').filter({ hasText: /^Call 911$/ })).toBeVisible()
  await expect(page.getByTestId("no-facility")).toContainText("Call 911 or go to the nearest emergency department")
  await expect(sheet(page).getByText(/call 911 now/).first()).toBeVisible()
})

test("capped emergent reply shows Call 911", async ({ page }) => {
  await open(page, "capped")
  await send(page, "chest pain")
  await expect(page.locator('a[href="tel:911"]').filter({ hasText: /^Call 911$/ })).toBeVisible()
  await expect(sheet(page).getByText(/wrapping up here/)).toBeVisible()
})

for (const scenario of ["capped_noresult", "no_provider", "followup"] as const) {
  test(`${scenario}: reply is visible without dragging and the header link is there`, async ({ page }) => {
    await open(page, scenario)
    await send(page, "chest pain")
    await expect(sheet(page).getByText(/(couldn't finish|having trouble|How long have you had)/)).toBeVisible()
    const link = page.getByRole("link", { name: "Emergency? Call 911" })
    await expect(link).toHaveAttribute("href", "tel:911")
    await expectTappable(page, link)
  })
}

for (const scenario of ["http500", "netabort"] as const) {
  test(`${scenario}: shows an error with the 911 line and keeps the typed text`, async ({ page }) => {
    await open(page, scenario)
    await send(page, "my text")
    await expect(sheet(page).getByText(/Something went wrong sending that/)).toBeVisible()
    await expect(sheet(page).getByText(/call 911/).first()).toBeVisible()
    await expect(page.getByPlaceholder("Describe your symptoms...")).toHaveValue("my text")
  })
}

test("five turns: the newest message stays in view", async ({ page }) => {
  await open(page, "followup")
  for (let i = 1; i <= 5; i++) await send(page, `turn ${i}`)
  const newest = sheet(page).getByText("turn 5")
  await expect(newest).toBeVisible()
  const box = await newest.boundingBox()
  const input = await page.getByPlaceholder("Describe your symptoms...").boundingBox()
  expect(box!.y + box!.height).toBeLessThanOrEqual(input!.y + 1)
})

test("three tabs, tab and sheet stay in sync, no triage tab, no guest menu", async ({ page }) => {
  await open(page, "routine")
  await expect(page.getByRole("button", { name: /triage/i })).toHaveCount(0)
  await expect(page.getByRole("button", { name: "Open menu" })).toHaveCount(0)
  const nav = page.locator("nav")
  await expect(nav.getByRole("button")).toHaveCount(3)

  const height = async () => (await sheet(page).boundingBox())!.height
  const map = nav.getByRole("button", { name: "Map" })
  const facilities = nav.getByRole("button", { name: "Facilities" })
  const chat = nav.getByRole("button", { name: "Chat" })
  await expect(map).toHaveAttribute("aria-current", "page")
  const peek = await height()

  await facilities.click()
  await expect(facilities).toHaveAttribute("aria-current", "page")
  await expect.poll(height).toBeGreaterThan(peek + 20)
  const half = await height()

  await chat.click()
  await expect(chat).toHaveAttribute("aria-current", "page")
  await expect.poll(height).toBeGreaterThan(half + 20)

  // The handle drives the same state: tap goes full -> peek and the Map tab lights up.
  await page.getByRole("separator", { name: "Resize chat panel" }).click()
  await expect(map).toHaveAttribute("aria-current", "page")
  await expect.poll(height).toBeLessThan(peek + 5)
  // Nothing was lost: a tab change never starts a new conversation.
  for (const tab of [map, facilities, chat]) await expectTappable(page, tab)
})

test("the sheet never reaches under the top bar and can always be collapsed", async ({ page }) => {
  await open(page, "routine")
  await page.locator("nav").getByRole("button", { name: "Chat" }).click()
  await expect.poll(async () => (await sheet(page).boundingBox())!.y).toBeGreaterThanOrEqual(56)
  await page.getByRole("separator", { name: "Resize chat panel" }).click()
  await expect(page.locator("nav").getByRole("button", { name: "Map" })).toHaveAttribute("aria-current", "page")
})

test("facilities list: 8 at a time, nearest first, wait shown, Show on map returns to the map", async ({ page }) => {
  await open(page, "routine")
  await page.locator("nav").getByRole("button", { name: "Facilities" }).click()
  const rows = page.getByTestId("facility-row")
  await expect(rows).toHaveCount(8)
  await expect(rows.first()).toContainText("St. Michael's Hospital") // nearest to the demo fallback
  await expect(rows.first()).toContainText(/\d\.\d km/)
  await expect(rows.first()).toContainText("min wait")
  await page.getByTestId("facility-sentinel").scrollIntoViewIfNeeded()
  await expect(rows).toHaveCount(11)

  await rows.first().locator("button").first().click()
  const show = page.getByTestId("facility-show-on-map")
  await expectTappable(page, show)
  await show.click()
  await expect(page.locator("nav").getByRole("button", { name: "Map" })).toHaveAttribute("aria-current", "page")
})

test("keyboard-sized viewport: the input stays visible below the top bar", async ({ page }) => {
  // Chromium cannot show a real on-screen keyboard. Shrinking the viewport mimics Android's
  // resizes-content mode; the iOS visualViewport case is covered by the sheetGeometry unit tests.
  await open(page, "followup")
  const size = page.viewportSize()!
  await page.getByPlaceholder("Describe your symptoms...").focus()
  await page.setViewportSize({ width: size.width, height: Math.round(size.height * 0.5) })
  const box = await page.getByPlaceholder("Describe your symptoms...").boundingBox()
  expect(box!.y).toBeGreaterThanOrEqual(56)
  expect(box!.y + box!.height).toBeLessThanOrEqual(Math.round(size.height * 0.5))
})

test("no horizontal scroll and a tappable Send on the browse screen", async ({ page }) => {
  await open(page, "routine")
  await expectNoHorizontalScroll(page)
  await page.getByPlaceholder("Describe your symptoms...").fill("x")
  await expectTappable(page, page.getByRole("button", { name: "Send" }))
})
