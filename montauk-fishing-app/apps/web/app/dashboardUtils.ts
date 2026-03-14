export type MapBbox = [number, number, number, number];

export type ZoneFactorExplanation = {
  factor: string;
  label: string;
  raw_value: string;
  score: number;
  weighted_contribution: number;
  reason: string;
};

export type ZoneScoreExplanation = {
  headline: string;
  summary: string;
  best_use_case_summary: string;
  confidence_score: number;
  watchouts: string[];
  top_reasons: string[];
  factors: ZoneFactorExplanation[];
};

export type RequestFailureState = {
  message: string;
  cooldown_until: number;
};

export type LayerSourceMetadata = {
  source: string;
  source_status?: string;
  fallback_used?: boolean;
  live_data_available?: boolean;
  provider_name?: string | null;
  dataset_id?: string | null;
  upstream_host?: string | null;
  attempted_urls?: string[] | null;
  provider_diagnostics?: Record<string, string | number | boolean | null> | null;
  requested_date?: string | null;
  failure_reason?: string | null;
  warning_messages?: string[] | null;
};

type ZoneExplanationSource = Partial<ZoneScoreExplanation> | null | undefined;

type ZoneExplanationFallbackInput = {
  score: number;
  name: string;
  sea_surface_temp_f: number;
  chlorophyll_mg_m3: number;
  current_speed_kts: number;
  score_breakdown?: Record<string, number>;
  weighted_score_breakdown?: Record<string, number>;
};

const requestFailureStates = new Map<string, RequestFailureState>();
const DEFAULT_REQUEST_FAILURE_COOLDOWN_MS = 15000;

export function formatBboxParam(bbox: MapBbox): string {
  return bbox.map((value) => value.toFixed(4)).join(",");
}

export function areBboxesEquivalent(left: MapBbox, right: MapBbox): boolean {
  return left.every((value, index) => Math.abs(value - right[index]) < 0.0001);
}

export function clampBboxToBounds(bbox: MapBbox, bounds: MapBbox): MapBbox {
  const [minLon, minLat, maxLon, maxLat] = bbox;
  const [boundsMinLon, boundsMinLat, boundsMaxLon, boundsMaxLat] = bounds;

  const clampedMinLon = Math.max(boundsMinLon, Math.min(minLon, boundsMaxLon));
  const clampedMaxLon = Math.max(boundsMinLon, Math.min(maxLon, boundsMaxLon));
  const clampedMinLat = Math.max(boundsMinLat, Math.min(minLat, boundsMaxLat));
  const clampedMaxLat = Math.max(boundsMinLat, Math.min(maxLat, boundsMaxLat));

  return [
    Math.min(clampedMinLon, clampedMaxLon),
    Math.min(clampedMinLat, clampedMaxLat),
    Math.max(clampedMinLon, clampedMaxLon),
    Math.max(clampedMinLat, clampedMaxLat),
  ];
}

export function formatZoneExplanationLabel(factor: string): string {
  return factor
    .split("_")
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(" ");
}

export function buildFallbackZoneExplanation(zone: ZoneExplanationFallbackInput): ZoneScoreExplanation {
  const weightedEntries = Object.entries(zone.weighted_score_breakdown ?? {}).sort((a, b) => b[1] - a[1]);
  const factors = weightedEntries.slice(0, 6).map(([factor, weightedContribution]) => ({
    factor,
    label: formatZoneExplanationLabel(factor),
    raw_value: "Available in zone signals",
    score: zone.score_breakdown?.[factor] ?? 0,
    weighted_contribution: weightedContribution,
    reason: "This factor is contributing meaningfully to the final zone score.",
  }));
  const topReasons = factors
    .filter((factor) => factor.weighted_contribution > 0)
    .slice(0, 3)
    .map((factor) => `${factor.label} is adding ${factor.weighted_contribution.toFixed(1)} points to this zone's score.`);

  return {
    headline: `${zone.name} is ranking well because multiple environmental signals are stacking in its favor.`,
    summary: `Score ${zone.score.toFixed(1)} with SST ${zone.sea_surface_temp_f.toFixed(1)} F, chlorophyll ${zone.chlorophyll_mg_m3.toFixed(2)} mg/m3, and current ${zone.current_speed_kts.toFixed(1)} kts.`,
    best_use_case_summary: "Best used as a high-priority scouting zone when multiple environmental signals are lining up.",
    confidence_score: Math.min(100, Math.round(zone.score * 0.9)),
    watchouts: ["Live water can shift quickly, so confirm the edge position when you arrive."],
    top_reasons: topReasons,
    factors,
  };
}

export function normalizeZoneExplanation(
  source: ZoneExplanationSource,
  fallbackInput: ZoneExplanationFallbackInput,
): ZoneScoreExplanation {
  const fallback = buildFallbackZoneExplanation(fallbackInput);

  return {
    headline: typeof source?.headline === "string" && source.headline.length > 0 ? source.headline : fallback.headline,
    summary: typeof source?.summary === "string" && source.summary.length > 0 ? source.summary : fallback.summary,
    best_use_case_summary:
      typeof source?.best_use_case_summary === "string" && source.best_use_case_summary.length > 0
        ? source.best_use_case_summary
        : fallback.best_use_case_summary,
    confidence_score:
      typeof source?.confidence_score === "number" && Number.isFinite(source.confidence_score)
        ? source.confidence_score
        : fallback.confidence_score,
    watchouts: Array.isArray(source?.watchouts) && source.watchouts.length > 0 ? source.watchouts : fallback.watchouts,
    top_reasons:
      Array.isArray(source?.top_reasons) && source.top_reasons.length > 0 ? source.top_reasons : fallback.top_reasons,
    factors: Array.isArray(source?.factors) && source.factors.length > 0 ? source.factors : fallback.factors,
  };
}

export function getRequestFailureState(key: string, now: number = Date.now()): RequestFailureState | null {
  const state = requestFailureStates.get(key) ?? null;
  if (!state) {
    return null;
  }
  if (state.cooldown_until <= now) {
    requestFailureStates.delete(key);
    return null;
  }
  return state;
}

export function rememberRequestFailure(
  key: string,
  message: string,
  cooldownMs: number = DEFAULT_REQUEST_FAILURE_COOLDOWN_MS,
  now: number = Date.now(),
): void {
  requestFailureStates.set(key, {
    message,
    cooldown_until: now + cooldownMs,
  });
}

export function clearRequestFailure(key: string): void {
  requestFailureStates.delete(key);
}

export function buildApiTimeoutMessage(path: string, timeoutMs: number, apiBaseUrl: string): string {
  return `Request timed out after ${timeoutMs} ms while requesting ${path} from ${apiBaseUrl}. The API may be slow, but it is not necessarily unavailable.`;
}

export function buildApiUnavailableMessage(path: string, apiBaseUrl: string): string {
  return `API unavailable at ${apiBaseUrl} while requesting ${path}. Check that the backend is running.`;
}

export function isApiUnavailableMessage(message: string | null | undefined): boolean {
  return typeof message === "string" && message.includes("API unavailable at");
}

export function buildLayerStatusMessage(layerLabel: string, metadata: LayerSourceMetadata | null | undefined): string | null {
  if (!metadata) {
    return null;
  }
  if (Array.isArray(metadata.warning_messages) && metadata.warning_messages.length > 0) {
    return metadata.warning_messages[0];
  }
  if (metadata.failure_reason === "network_blocked") {
    return `Live ${layerLabel} is blocked from reaching ${metadata.upstream_host ?? "the upstream host"} in this environment, so a fallback estimate is being used.`;
  }
  if (metadata.failure_reason === "dns_error") {
    return `Live ${layerLabel} could not resolve the upstream host, so a fallback estimate is being used.`;
  }
  if (metadata.failure_reason === "timeout") {
    return `Live ${layerLabel} timed out upstream, so a fallback estimate is being used.`;
  }
  if (metadata.failure_reason === "invalid_dataset") {
    return `The configured live ${layerLabel} dataset could not be resolved upstream, so a fallback estimate is being used.`;
  }
  if (metadata.failure_reason === "unsupported_date") {
    return `Live ${layerLabel} was unavailable for the selected date, so a fallback estimate is being used.`;
  }
  if (metadata.failure_reason === "parse_error" || metadata.failure_reason === "empty_dataset") {
    return `Live ${layerLabel} returned no usable values for this request, so a fallback estimate is being used.`;
  }
  if (metadata.source === "cached_real") {
    return `Showing last-known-good real ${layerLabel} data while live ${layerLabel} feeds are unavailable.`;
  }
  if (metadata.source === "processed") {
    return `Showing cached ${layerLabel} data while live ${layerLabel} is unavailable.`;
  }
  if (metadata.source === "mock_fallback") {
    return `Showing a local ${layerLabel} estimate while live ${layerLabel} is unavailable.`;
  }
  if (metadata.source === "unavailable") {
    return metadata.failure_reason
      ? `${layerLabel} data unavailable for this request (${metadata.failure_reason}).`
      : `${layerLabel} data unavailable for this request.`;
  }
  return null;
}
