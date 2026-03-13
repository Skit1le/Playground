from __future__ import annotations

from datetime import date

from app.schemas import (
    SstMapFeature,
    SstMapFeatureCollection,
    SstMapFeatureProperties,
    SstMapMetadata,
    SstMapPointGeometry,
    SstMapResponse,
)
from app.sst_provider import SstDataUnavailableError, SstProvider


class SstMapService:
    def __init__(self, sst_provider: SstProvider):
        self.sst_provider = sst_provider

    def get_sst_map(
        self,
        *,
        trip_date: date,
        bbox: tuple[float, float, float, float],
    ) -> SstMapResponse:
        min_lng, min_lat, max_lng, max_lat = bbox
        try:
            points = self.sst_provider.get_sst_points(
                trip_date,
                min_lat=min_lat,
                max_lat=max_lat,
                min_lon=min_lng,
                max_lon=max_lng,
            )
            source = getattr(
                self.sst_provider,
                "last_source_name",
                getattr(self.sst_provider, "source_name", "unknown"),
            )
        except (SstDataUnavailableError, Exception):
            points = ()
            source = "unavailable"

        temps = [point.sea_surface_temp_f for point in points]
        temp_range = [round(min(temps), 1), round(max(temps), 1)] if temps else None

        return SstMapResponse(
            metadata=SstMapMetadata(
                date=trip_date,
                bbox=[min_lng, min_lat, max_lng, max_lat],
                source=source,
                point_count=len(points),
                temp_range_f=temp_range,
            ),
            data=SstMapFeatureCollection(
                features=[
                    SstMapFeature(
                        geometry=SstMapPointGeometry(coordinates=[point.longitude, point.latitude]),
                        properties=SstMapFeatureProperties(
                            sea_surface_temp_f=round(point.sea_surface_temp_f, 1),
                        ),
                    )
                    for point in points
                ]
            ),
        )
