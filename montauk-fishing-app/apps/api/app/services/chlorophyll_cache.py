from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path

from app.chlorophyll_provider import CachedChlorophyllSnapshotAdapter, ChlorophyllProvider
from app.schemas import (
    ChlorophyllCacheEntry,
    ChlorophyllCacheInspectionResponse,
    ChlorophyllCacheWarmResponse,
    ChlorophyllCacheWarmResult,
)


def _round_bbox(bbox: tuple[float, float, float, float]) -> list[float]:
    return [round(value, 4) for value in bbox]


def _parse_snapshot_payload(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def _parse_requested_date(value: object) -> date:
    if isinstance(value, str):
        return date.fromisoformat(value)
    raise ValueError("Snapshot payload is missing a valid requested_date.")


def _calculate_age_hours(cached_at: object) -> float | None:
    if not isinstance(cached_at, str) or not cached_at:
        return None
    normalized = cached_at.replace("Z", "+00:00")
    try:
        cached_at_dt = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if cached_at_dt.tzinfo is None:
        cached_at_dt = cached_at_dt.replace(tzinfo=timezone.utc)
    age = datetime.now(timezone.utc) - cached_at_dt.astimezone(timezone.utc)
    return round(age.total_seconds() / 3600, 2)


@dataclass(frozen=True)
class ChlorophyllCacheWarmRequest:
    requested_dates: tuple[date, ...]
    bboxes: tuple[tuple[float, float, float, float], ...]
    mode: str = "live"


class ChlorophyllCacheService:
    def __init__(
        self,
        *,
        cache_adapter: CachedChlorophyllSnapshotAdapter,
        live_provider: ChlorophyllProvider,
        processed_provider: ChlorophyllProvider,
    ):
        self.cache_adapter = cache_adapter
        self.live_provider = live_provider
        self.processed_provider = processed_provider

    @property
    def cache_dir(self) -> Path:
        return self.cache_adapter.cache_dir

    def inspect_cache(self) -> ChlorophyllCacheInspectionResponse:
        entries: list[ChlorophyllCacheEntry] = []
        if not self.cache_dir.exists():
            return ChlorophyllCacheInspectionResponse(
                cache_dir=str(self.cache_dir),
                entry_count=0,
                entries=[],
            )

        for path in sorted(self.cache_dir.rglob("*.json")):
            payload = _parse_snapshot_payload(path)
            points = payload.get("points", [])
            entries.append(
                ChlorophyllCacheEntry(
                    requested_date=_parse_requested_date(payload.get("requested_date")),
                    resolved_timestamp=payload.get("resolved_timestamp") if isinstance(payload.get("resolved_timestamp"), str) else None,
                    source=str(payload.get("seed_source") or "unknown"),
                    dataset_id=payload.get("dataset_id") if isinstance(payload.get("dataset_id"), str) else None,
                    bbox=[float(value) for value in payload.get("bbox", [])],
                    cache_key=str(payload.get("cache_key") or path.stem),
                    cache_path=str(path),
                    cached_at=payload.get("cached_at") if isinstance(payload.get("cached_at"), str) else None,
                    age_hours=_calculate_age_hours(payload.get("cached_at")),
                    upstream_host=payload.get("upstream_host") if isinstance(payload.get("upstream_host"), str) else None,
                    attempted_urls=[
                        str(value) for value in (payload.get("attempted_urls") or []) if isinstance(value, str)
                    ],
                    provider_diagnostics={
                        str(key): value
                        for key, value in (payload.get("provider_diagnostics") or {}).items()
                    },
                    point_count=len(points) if isinstance(points, list) else 0,
                )
            )

        entries.sort(key=lambda entry: (entry.requested_date, entry.cache_path), reverse=True)
        return ChlorophyllCacheInspectionResponse(
            cache_dir=str(self.cache_dir),
            entry_count=len(entries),
            entries=entries,
        )

    def warm_cache(self, request: ChlorophyllCacheWarmRequest) -> ChlorophyllCacheWarmResponse:
        provider = self.live_provider if request.mode == "live" else self.processed_provider
        results: list[ChlorophyllCacheWarmResult] = []

        for requested_date in request.requested_dates:
            for bbox in request.bboxes:
                min_lng, min_lat, max_lng, max_lat = bbox
                try:
                    points = provider.get_chlorophyll_points(
                        requested_date,
                        min_lat=min_lat,
                        max_lat=max_lat,
                        min_lon=min_lng,
                        max_lon=max_lng,
                    )
                    normalized_bbox = (
                        min_lat,
                        max_lat,
                        min_lng,
                        max_lng,
                    )
                    self.cache_adapter.store_snapshot(
                        requested_date=requested_date.isoformat(),
                        bbox=normalized_bbox,
                        points=points,
                        dataset_id=getattr(provider, "last_dataset_id", None),
                        resolved_timestamp=getattr(provider, "last_resolved_timestamp", "") or requested_date.isoformat(),
                        upstream_host=getattr(provider, "last_upstream_host", None),
                        attempted_urls=list(getattr(provider, "last_attempted_urls", []) or []),
                        provider_diagnostics=dict(getattr(provider, "last_provider_diagnostics", {}) or {}),
                        seed_source=getattr(provider, "last_source_name", getattr(provider, "source_name", request.mode)),
                    )
                    exact_path, _ = self.cache_adapter._paths(requested_date.isoformat(), normalized_bbox)
                    results.append(
                        ChlorophyllCacheWarmResult(
                            requested_date=requested_date,
                            bbox=_round_bbox(bbox),
                            success=True,
                            source=getattr(provider, "last_source_name", getattr(provider, "source_name", request.mode)),
                            dataset_id=getattr(provider, "last_dataset_id", None),
                            cache_key=f"{requested_date.isoformat()}|{min_lng},{min_lat},{max_lng},{max_lat}",
                            cache_path=str(exact_path),
                            resolved_timestamp=getattr(provider, "last_resolved_timestamp", "") or requested_date.isoformat(),
                            point_count=len(points),
                            warning_messages=[],
                        )
                    )
                except Exception as exc:
                    failure_reason = getattr(provider, "last_failure_reason", "") or str(exc)
                    results.append(
                        ChlorophyllCacheWarmResult(
                            requested_date=requested_date,
                            bbox=_round_bbox(bbox),
                            success=False,
                            source=getattr(provider, "last_source_name", getattr(provider, "source_name", request.mode)),
                            dataset_id=getattr(provider, "last_dataset_id", None),
                            resolved_timestamp=getattr(provider, "last_resolved_timestamp", "") or None,
                            point_count=0,
                            failure_reason=failure_reason,
                            warning_messages=[f"Unable to warm chlorophyll cache for this request ({failure_reason})."],
                        )
                    )

        warmed_count = sum(1 for result in results if result.success)
        failed_count = len(results) - warmed_count
        return ChlorophyllCacheWarmResponse(
            requested_dates=list(request.requested_dates),
            bboxes=[_round_bbox(bbox) for bbox in request.bboxes],
            mode="processed" if request.mode == "processed" else "live",
            warmed_count=warmed_count,
            failed_count=failed_count,
            results=results,
        )
