import { expect, type Page, test } from "@playwright/test";

async function mockAuth(page: Page): Promise<void> {
  await page.route("**/api/v1/admin/me", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        id: "11111111-1111-1111-1111-111111111111",
        username: "robertas",
        email: "r@etanetas.lt",
        role: "admin",
        active: true,
        lms_username: null,
        created_at: "2026-05-20T12:00:00Z",
      }),
    });
  });
}

async function seedAuthSession(page: Page): Promise<void> {
  await page.addInitScript(() => {
    window.localStorage.setItem("eta_key", "etn_pk_test_key");
    window.localStorage.setItem("eta_url", "http://localhost:8000");
  });
}

test("setup redirects to dashboard", async ({ page }) => {
  await mockAuth(page);
  await page.route("**/api/v1/admin/coverage/stats", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        total_buildings: 100,
        covered_buildings: 40,
        address_offerings_count: 3,
        zones_count: 2,
        zones_with_polygon: 2,
        zone_offerings_count: 2,
        addresses_by_status: [{ status: "available", count: 2 }],
        top_uncovered_localities: [],
        scope: "operational",
        scope_label: "Obszar operacyjny",
        scope_municipalities: ["Vilniaus miesto", "Vilniaus rajono", "Šalčininkų rajono"],
      }),
    });
  });
  await page.route("**/api/v1/admin/bulk-operations", async (route) => {
    await route.fulfill({ status: 200, contentType: "application/json", body: "[]" });
  });

  await page.goto("/setup");
  await page.getByPlaceholder("etn_pk_...").fill("etn_pk_test_key");
  await page.getByRole("button", { name: "Połącz" }).click();

  await expect(page.getByRole("heading", { name: "Dashboard" })).toBeVisible();
});

test("addresses bulk preview execute undo flow", async ({ page }) => {
  await seedAuthSession(page);
  await mockAuth(page);
  await page.route("**/api/v1/admin/counties", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify([{ rc_code: 1, name: "Vilniaus" }]),
    });
  });
  await page.route("**/api/v1/admin/technologies", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify([
        {
          id: "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
          type_id: "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
          variant_code: "gpon",
          display_name: "GPON",
          theoretical_max_dl_mbps: 2500,
          theoretical_max_ul_mbps: 1250,
          sort_order: 100,
          active: true,
        },
      ]),
    });
  });
  await page.route("**/api/v1/admin/addresses/search", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify([
        {
          rc_code: 1001,
          full_address: "Vilniaus g. 12, Vilnius",
          postal_code: "LT-01100",
          address_type: "building",
        },
      ]),
    });
  });
  await page.route("**/api/v1/admin/addresses/1001/offerings", async (route) => {
    await route.fulfill({ status: 200, contentType: "application/json", body: "[]" });
  });
  await page.route("**/api/v1/admin/bulk/preview", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        affected_count: 1,
        sample: [],
        preview_token: "tmp_abc123",
      }),
    });
  });
  await page.route("**/api/v1/admin/bulk/execute", async (route) => {
    await route.fulfill({
      status: 201,
      contentType: "application/json",
      body: JSON.stringify({
        bulk_operation_id: "cccccccc-cccc-cccc-cccc-cccccccccccc",
        modified_count: 1,
      }),
    });
  });
  await page.route("**/api/v1/admin/bulk/*/rollback", async (route) => {
    await route.fulfill({ status: 204, body: "" });
  });

  await page.goto("/addresses");
  await page.getByPlaceholder("Szukaj adresu (min. 2 znaki)").fill("Vil");
  await page.getByRole("button", { name: "Szukaj", exact: true }).click();
  await expect(page.getByText("Vilniaus g. 12, Vilnius")).toBeVisible();
  await page.locator('input[type="checkbox"]').last().check();
  await expect(page.getByText("Zaznaczono: 1")).toBeVisible();
  await page
    .locator('select:has(option[value="aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"])')
    .selectOption("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa");
  await page.getByRole("button", { name: "Preview" }).click();
  await expect(page.getByText(/Preview gotowy:/).first()).toBeVisible();
  await page.getByRole("button", { name: "Wykonaj" }).click();
  await page.getByRole("button", { name: "Cofnij ostatnią operację" }).click();
});

test("map page loads and supports zone details", async ({ page }) => {
  await seedAuthSession(page);
  await mockAuth(page);
  await page.route("**/api/v1/admin/technologies", async (route) => {
    await route.fulfill({ status: 200, contentType: "application/json", body: "[]" });
  });
  await page.route("**/api/v1/admin/map/zones/geojson", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        type: "FeatureCollection",
        features: [
          {
            type: "Feature",
            geometry: {
              type: "Polygon",
              coordinates: [
                [
                  [25.26, 54.68],
                  [25.27, 54.68],
                  [25.27, 54.69],
                  [25.26, 54.69],
                  [25.26, 54.68],
                ],
              ],
            },
            properties: {
              id: "dddddddd-dddd-dddd-dddd-dddddddddddd",
              name: "Eišiškės centrum",
              priority: 100,
              offerings: [],
            },
          },
        ],
      }),
    });
  });
  await page.route(
    "**/api/v1/admin/zones/dddddddd-dddd-dddd-dddd-dddddddddddd/detail",
    async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          id: "dddddddd-dddd-dddd-dddd-dddddddddddd",
          name: "Eišiškės centrum",
          description: null,
          priority: 100,
          has_polygon: true,
          polygon_geojson: null,
          created_at: "2026-05-20T12:00:00Z",
          offerings: [],
          address_count: 234,
        }),
      });
    },
  );
  await page.route("**/api/v1/admin/addresses/search", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify([
        {
          rc_code: 2002,
          full_address: "Eišiškių g. 1, Šalčininkai",
          postal_code: "LT-17100",
          address_type: "building",
        },
      ]),
    });
  });
  await page.route("**/api/v1/admin/addresses/2002", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        rc_code: 2002,
        full_address: "Eišiškių g. 1, Šalčininkai",
        postal_code: "LT-17100",
        address_type: "building",
        locality_code: 1,
        locality_name: "Šalčininkai",
        street_code: 2,
        street_name: "Eišiškių g.",
        house_no: "1",
        corpus_no: null,
        flat_no: null,
        lon: 25.38,
        lat: 54.31,
      }),
    });
  });
  await page.route("**/api/v1/admin/map/addresses?*", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ type: "FeatureCollection", features: [] }),
    });
  });

  await page.goto("/map");
  await expect(page.getByText("Szczegóły strefy")).toBeVisible();
  await page.getByPlaceholder("Wpisz adres...").fill("Eiš");
  await page.getByRole("button", { name: "Eišiškių g. 1, Šalčininkai" }).click();
  await expect(page.getByText("Szczegóły adresu")).toBeVisible();
});

test("users page creates and revokes api key", async ({ page }) => {
  await seedAuthSession(page);
  await mockAuth(page);
  await page.route("**/api/v1/admin/users", async (route) => {
    if (route.request().method() === "GET") {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify([
          {
            id: "eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee",
            username: "robertas",
            email: "r@etanetas.lt",
            role: "admin",
            active: true,
            lms_username: null,
            created_at: "2026-05-20T12:00:00Z",
          },
        ]),
      });
      return;
    }
    await route.fulfill({
      status: 201,
      contentType: "application/json",
      body: JSON.stringify({
        id: "ffffffff-ffff-ffff-ffff-ffffffffffff",
        username: "newuser",
        email: "new@etanetas.lt",
        role: "viewer",
        active: true,
        lms_username: null,
        created_at: "2026-05-20T12:10:00Z",
      }),
    });
  });
  await page.route(
    "**/api/v1/admin/users/eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee/api-keys",
    async (route) => {
      if (route.request().method() === "GET") {
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify([
            {
              id: "11112222-3333-4444-5555-666677778888",
              name: "main",
              created_at: "2026-05-20T12:00:00Z",
              last_used_at: null,
              expires_at: null,
              revoked_at: null,
            },
          ]),
        });
        return;
      }
      await route.fulfill({
        status: 201,
        contentType: "application/json",
        body: JSON.stringify({
          id: "99990000-aaaa-bbbb-cccc-ddddeeeeffff",
          name: "main",
          created_at: "2026-05-20T12:11:00Z",
          last_used_at: null,
          expires_at: null,
          revoked_at: null,
          raw_key: "etn_pk_generated_raw_key",
        }),
      });
    },
  );
  await page.route("**/api/v1/admin/api-keys/*", async (route) => {
    await route.fulfill({ status: 204, body: "" });
  });

  await page.goto("/users");
  await page.getByRole("button", { name: "Odśwież klucze" }).click();
  await page.getByRole("button", { name: "Generuj klucz" }).click();
  await expect(page.getByText("etn_pk_generated_raw_key")).toBeVisible();
  await page.getByRole("button", { name: "Revoke" }).click();
});
