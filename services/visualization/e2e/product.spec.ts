import { expect, test, type Page } from "@playwright/test";

async function endpoints(page: Page) {
  await expect(page.getByRole("textbox", { name: "Origin", exact: true })).not.toHaveValue("");
  await page.getByRole("textbox", { name: "Origin", exact: true }).fill("12.9750564233, 77.5903035618");
  await page.getByRole("button", { name: "Confirm origin", exact: true }).click();
  await page.getByRole("textbox", { name: "Destination", exact: true }).fill("12.9798218, 77.6009173");
  await page.getByRole("button", { name: "Confirm destination", exact: true }).click();
  await expect(page.getByRole("button", { name: "Balanced route", exact: true })).toBeVisible();
}

test("real routes, vehicles, modes, heatmap and responsive controls", async ({ page }, info) => {
  const errors: string[] = [];
  const failures: string[] = [];
  const responses: unknown[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  page.on("console", (message) => { if (message.type() === "error") errors.push(message.text()); });
  page.on("requestfailed", (request) => {
    if (!request.failure()?.errorText.includes("ERR_ABORTED")) failures.push(`${request.url()} ${request.failure()?.errorText}`);
  });
  page.on("response", async (response) => {
    if (response.url().endsWith("/api/route") && response.status() === 200) responses.push(await response.json());
    if (response.status() >= 400) failures.push(`${response.status()} ${response.url()}`);
  });
  await page.goto("/");
  await expect(page.locator(".leaflet-container")).toBeVisible();
  await endpoints(page);
  for (const vehicle of ["Scooter", "Bike", "Truck", "Car"]) {
    await page.getByRole("button", { name: vehicle, exact: true }).click();
    await expect(page.getByRole("button", { name: vehicle, exact: true })).toHaveAttribute("aria-pressed", "true");
    await expect(page.getByText(`Moving-time ETA estimate · ${vehicle.toLowerCase()}`, { exact: true })).toHaveCount(3);
    for (const [priority, route] of [["Fastest", "Fastest"], ["Balanced", "Balanced"], ["Connected", "Most Connected"]]) {
      await page.getByRole("button", { name: `${priority} priority`, exact: true }).click();
      await expect(page.getByRole("button", { name: `${route} route`, exact: true })).toHaveAttribute("aria-pressed", "true");
    }
  }
  await expect(page.getByText(/Unknown signal provenance|Model or fallback estimate/, { exact: false }).first()).toBeVisible();
  await expect(page.getByText(/0% provider-backed/).first()).toBeVisible();
  const tile = page.waitForResponse((response) => response.url().includes("/api/tiles/") && response.status() === 200);
  await page.getByRole("button", { name: "Toggle heatmap" }).click();
  await tile;
  await expect(page.getByRole("button", { name: "Toggle heatmap" })).toHaveAttribute("aria-pressed", "true");
  await page.getByRole("button", { name: "Toggle heatmap" }).click();
  await page.getByRole("button", { name: "Toggle heatmap" }).click();
  await page.getByRole("button", { name: "Toggle heatmap" }).click();
  await page.getByRole("button", { name: "Switch to dark mode" }).click();
  await page.getByRole("button", { name: "Switch to light mode" }).click();
  const layout = await page.evaluate(() => ({ width: innerWidth, overflow: document.documentElement.scrollWidth > innerWidth,
    map: document.querySelector(".leaflet-container")!.getBoundingClientRect().toJSON(),
    routeCanvases: document.querySelectorAll(".leaflet-overlay-pane canvas").length,
    tiles: [...document.querySelectorAll<HTMLImageElement>("img.leaflet-tile")].filter((image) => image.complete && image.naturalWidth > 0).length,
  }));
  expect(layout.overflow).toBe(false);
  expect(layout.map.width).toBe(layout.width);
  expect(layout.routeCanvases).toBeGreaterThan(0);
  expect(layout.tiles).toBeGreaterThan(0);
  await page.screenshot({ path: info.outputPath("product.png"), fullPage: true });
  await info.attach("runtime-evidence", { body: JSON.stringify({ layout, errors, failures, responses }, null, 2), contentType: "application/json" });
  expect(errors).toEqual([]);
  expect(failures).toEqual([]);
});

test("invalid input, no route, recovery and changed inputs", async ({ page }) => {
  await page.goto("/");
  await endpoints(page);
  const origin = page.getByRole("textbox", { name: "Origin", exact: true });
  await origin.fill("91, 77.59");
  await page.getByRole("button", { name: "Confirm origin" }).click();
  await expect(page.getByText("Coordinates must be valid latitude and longitude values")).toBeVisible();
  await expect(page.getByText("Set origin and destination to load routes.")).toBeVisible();
  await origin.fill("12.9798218, 77.6009173");
  await page.getByRole("button", { name: "Confirm origin" }).click();
  await expect(page.getByText(/No route found/).first()).toBeVisible();
  await expect(page.getByRole("button", { name: "Retry", exact: true })).toBeVisible();
  await endpoints(page);
  await expect(page.getByRole("button", { name: "Fastest route" })).toContainText("2.9 min");
  await page.getByRole("textbox", { name: "Destination", exact: true }).fill("Unconfirmed endpoint");
  await expect(page.getByRole("button", { name: "Balanced route" })).toHaveCount(0);
  await expect(page.getByText("Set origin and destination to load routes.")).toBeVisible();
});

test("controlled service errors and loading recover to real routes", async ({ page }) => {
  // Fault injection covers UI handling only; subsequent success uses real services.
  await page.route("**/api/ready/prediction", (route) => route.fulfill({ status: 503, json: { model_ready: false } }));
  await page.route("**/api/route", (route) => route.fulfill({ status: 202, headers: { "Retry-After": "1" }, json: { status: "loading", retry_after: 1 } }));
  await page.goto("/");
  await expect(page.getByText(/Prediction unavailable/)).toBeVisible();
  await expect(page.getByText(/Loading Bangalore road network/)).toBeVisible();
  await page.unroute("**/api/route");
  await endpoints(page);
  await page.route("**/api/route", (route) => route.fulfill({ status: 502, contentType: "text/html", body: "<html>private proxy stack trace</html>" }));
  await page.getByRole("button", { name: "Bike", exact: true }).click();
  await expect(page.getByText("Route request failed", { exact: true }).first()).toBeVisible();
  await expect(page.getByText(/private proxy/)).toHaveCount(0);
  await page.unroute("**/api/route");
  await page.getByRole("button", { name: "Retry", exact: true }).click();
  await expect(page.getByText("Moving-time ETA estimate · bike", { exact: true })).toHaveCount(3);
});

test("unavailable data has a visible retry path", async ({ page }) => {
  await page.route("**/api/cities", (route) => route.abort("connectionrefused"));
  await page.goto("/");
  await expect(page.getByRole("button", { name: "Retry services" })).toBeVisible();
  await expect(page.getByText("Set origin and destination to load routes.")).toBeVisible();
  await page.unroute("**/api/cities");
  await page.getByRole("button", { name: "Retry services" }).click();
  await endpoints(page);
});

test("map-picked endpoints and scrollable route explanations", async ({ page }, info) => {
  await page.goto("/");
  await endpoints(page);
  // Wait for the endpoint fly-to before picking actual points on the loaded map.
  await page.waitForTimeout(1800);
  const viewport = page.viewportSize()!;
  const origin = page.getByRole("textbox", { name: "Origin", exact: true });
  const destination = page.getByRole("textbox", { name: "Destination", exact: true });
  const originalOrigin = await origin.inputValue();
  const originalDestination = await destination.inputValue();
  const x = Math.round(viewport.width * 0.67);
  await origin.focus();
  await page.locator(".leaflet-container").click({ position: { x, y: 355 } });
  await expect(origin).not.toHaveValue(originalOrigin);
  await destination.focus();
  await page.locator(".leaflet-container").click({ position: { x: x - 45, y: 420 } });
  await expect(destination).not.toHaveValue(originalDestination);
  await expect(page.getByRole("button", { name: "Balanced route", exact: true })).toBeVisible();
  const explanations = page.getByRole("button", { name: "Explain", exact: true });
  await expect(explanations).toHaveCount(3);
  // Scroll each real card into view, open its details, and close it again.
  for (let index = 0; index < 3; index += 1) {
    const button = explanations.nth(index);
    await button.click();
    await expect(page.getByText("Connectivity", { exact: true })).toBeVisible();
    await expect(page.getByText("Speed", { exact: true })).toBeVisible();
    await button.click();
  }
  await explanations.last().click();
  await page.getByText("Risk", { exact: true }).scrollIntoViewIfNeeded();
  expect(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth)).toBe(false);
  await page.screenshot({ path: info.outputPath("map-picks-and-details.png"), fullPage: true });
});
