import { expect, test } from "@playwright/test";

test("production assets, SPA reload and real gateway inference", async ({ page, request }) => {
  test.skip(!process.env.E2E_RELEASE, "Requires the actual production Compose gateway");
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  const assets: { url: string; status: number; type: string; cache: string }[] = [];
  page.on("response", (response) => {
    if (response.url().includes("/assets/")) assets.push({ url: response.url(), status: response.status(),
      type: response.headers()["content-type"], cache: response.headers()["cache-control"] });
  });
  const document = await page.goto("/inspect-route");
  expect(document?.headers()["cache-control"]).toBe("no-cache");
  expect(document?.headers()["x-frame-options"]).toBe("DENY");
  expect(document?.headers()["x-content-type-options"]).toBe("nosniff");
  await expect(page.locator(".leaflet-container")).toBeVisible();
  await expect(page.getByRole("button", { name: "Balanced route", exact: true })).toBeVisible();
  await page.reload();
  await expect(page.getByRole("button", { name: "Balanced route", exact: true })).toBeVisible();
  for (const name of ["data", "routing", "prediction"]) {
    expect((await request.get(`/api/ready/${name}`)).status()).toBe(200);
  }
  const prediction = await request.post("/api/predict", { data: { city: "bangalore", hour_of_day: 12,
    segments: [{ id: "browser-release", lat: 12.975, lon: 77.59, highway: "primary", length: 100 }] } });
  expect(prediction.status()).toBe(200);
  expect((await prediction.json()).confidence).toBeNull();
  expect((await request.get("/api/test-route/bangalore")).status()).toBe(404);
  expect((await request.get("/api/memory")).status()).toBe(404);
  expect((await request.delete("/api/route")).status()).toBe(403);
  const crossOrigin = await request.get("/api/cities", { headers: { Origin: "https://unapproved.example" } });
  expect(crossOrigin.headers()["access-control-allow-origin"]).toBeUndefined();
  const oversized = await request.post("/api/predict", { data: { padding: "x".repeat(1_100_000) } });
  expect(oversized.status()).toBe(413);
  // Controlled provider failure covers presentation; inference/routes above
  // and in product.spec.ts always use the real production services.
  await page.route("**/api/geocode?*", (route) => route.fulfill({ status: 503,
    json: { detail: "Place search unavailable. Enter latitude, longitude or pick the map." } }));
  await page.getByRole("textbox", { name: "Origin", exact: true }).fill("Unavailable place");
  await page.getByRole("button", { name: "Confirm origin", exact: true }).click();
  await expect(page.getByText("Place search unavailable. Enter latitude, longitude or pick the map.")).toBeVisible();
  await expect(page.getByRole("button", { name: "Balanced route", exact: true })).toHaveCount(0);
  await page.unroute("**/api/geocode?*");
  expect(assets.length).toBeGreaterThan(2);
  for (const asset of assets) {
    expect(asset.status).toBe(200);
    expect(asset.type).toMatch(/javascript|css/);
    expect(asset.cache).toContain("immutable");
  }
  expect(errors).toEqual([]);
});
