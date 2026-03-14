import assert from "node:assert/strict";

import {
  areBboxesEquivalent,
  clampBboxToBounds,
  buildApiTimeoutMessage,
  buildApiUnavailableMessage,
  buildLayerStatusMessage,
  clearRequestFailure,
  formatBboxParam,
  getRequestFailureState,
  isApiUnavailableMessage,
  rememberRequestFailure,
  normalizeZoneExplanation,
  type MapBbox,
} from "./dashboardUtils.ts";

function runDashboardUtilsAssertions(): void {
  const bbox: MapBbox = [-72.28004, 40.62001, -71.02002, 41.18003];
  assert.equal(formatBboxParam(bbox), "-72.2800,40.6200,-71.0200,41.1800");

  const stableLeft: MapBbox = [-72.28, 40.62, -71.02, 41.18];
  const stableRight: MapBbox = [-72.28004, 40.62004, -71.02004, 41.18004];
  assert.equal(areBboxesEquivalent(stableLeft, stableRight), true);

  const changedRight: MapBbox = [-72.18, 40.62, -70.92, 41.18];
  assert.equal(areBboxesEquivalent(stableLeft, changedRight), false);

  const expandedBbox: MapBbox = [-74.1961, 25.0147, -67.296, 42.3205];
  assert.deepEqual(clampBboxToBounds(expandedBbox, stableLeft), stableLeft);

  const partiallyShiftedBbox: MapBbox = [-72.15, 40.7, -70.5, 41.3];
  assert.deepEqual(clampBboxToBounds(partiallyShiftedBbox, stableLeft), [-72.15, 40.7, -71.02, 41.18]);

  const explanation = normalizeZoneExplanation(
    {
      headline: "Live payload headline",
      summary: "Short summary",
    },
    {
      name: "Hudson Edge",
      score: 84.2,
      sea_surface_temp_f: 67.4,
      chlorophyll_mg_m3: 0.28,
      current_speed_kts: 1.5,
      score_breakdown: { temp_suitability: 92 },
      weighted_score_breakdown: { temp_suitability: 18.4 },
    },
  );

  assert.equal(explanation.headline, "Live payload headline");
  assert.equal(explanation.summary, "Short summary");
  assert.ok(explanation.best_use_case_summary.length > 0);
  assert.equal(typeof explanation.confidence_score, "number");
  assert.ok(explanation.watchouts.length > 0);
  assert.ok(explanation.top_reasons.length > 0);
  assert.ok(explanation.factors.length > 0);

  rememberRequestFailure("zones:2026-03-11:bluefin", "timed out", 3000, 1000);
  const activeFailure = getRequestFailureState("zones:2026-03-11:bluefin", 2000);
  assert.equal(activeFailure?.message, "timed out");
  assert.equal(getRequestFailureState("zones:2026-03-11:bluefin", 5000), null);

  rememberRequestFailure("sst:2026-03-11:bbox", "overlay failed");
  clearRequestFailure("sst:2026-03-11:bbox");
  assert.equal(getRequestFailureState("sst:2026-03-11:bbox"), null);

  assert.equal(
    buildLayerStatusMessage("SST", {
      source: "processed",
      warning_messages: ["Showing cached SST data while live SST is unavailable."],
    }),
    "Showing cached SST data while live SST is unavailable.",
  );
  assert.equal(
    buildLayerStatusMessage("chlorophyll", {
      source: "mock_fallback",
      failure_reason: "network_blocked",
      upstream_host: "coastwatch.pfeg.noaa.gov",
    }),
    "Live chlorophyll is blocked from reaching coastwatch.pfeg.noaa.gov in this environment, so a fallback estimate is being used.",
  );
  assert.equal(
    buildApiTimeoutMessage("/map/sst?date=2026-03-11", 5000, "http://127.0.0.1:8000"),
    "Request timed out after 5000 ms while requesting /map/sst?date=2026-03-11 from http://127.0.0.1:8000. The API may be slow, but it is not necessarily unavailable.",
  );
  assert.equal(
    buildApiUnavailableMessage("/health", "http://127.0.0.1:8000"),
    "API unavailable at http://127.0.0.1:8000 while requesting /health. Check that the backend is running.",
  );
  assert.equal(isApiUnavailableMessage("API unavailable at http://127.0.0.1:8000 while requesting /health. Check that the backend is running."), true);
  assert.equal(isApiUnavailableMessage("Request timed out after 5000 ms while requesting /map/sst from http://127.0.0.1:8000. The API may be slow, but it is not necessarily unavailable."), false);
}

runDashboardUtilsAssertions();
console.log("dashboardUtils assertions passed");
