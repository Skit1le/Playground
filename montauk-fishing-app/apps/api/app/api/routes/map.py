from datetime import date
import logging

from fastapi import APIRouter, HTTPException, Query, status

from app.api.deps import SstMapServiceDep
from app.schemas import SstMapResponse

router = APIRouter(prefix="/map", tags=["map"])
logger = logging.getLogger(__name__)


def _parse_bbox(value: str) -> tuple[float, float, float, float]:
    try:
        min_lng_text, min_lat_text, max_lng_text, max_lat_text = value.split(",")
        bbox = (
            float(min_lng_text),
            float(min_lat_text),
            float(max_lng_text),
            float(max_lat_text),
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="bbox must be 'minLng,minLat,maxLng,maxLat'.",
        ) from exc

    min_lng, min_lat, max_lng, max_lat = bbox
    if min_lng >= max_lng or min_lat >= max_lat:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="bbox must be ordered as minLng,minLat,maxLng,maxLat.",
        )
    return bbox


@router.get("/sst", response_model=SstMapResponse)
def get_sst_map(
    sst_map_service: SstMapServiceDep,
    date_value: date = Query(alias="date"),
    bbox: str = Query(),
) -> SstMapResponse:
    parsed_bbox = _parse_bbox(bbox)
    logger.info(
        "Handling /map/sst request",
        extra={
            "trip_date": date_value.isoformat(),
            "bbox": list(parsed_bbox),
        },
    )
    return sst_map_service.get_sst_map(
        trip_date=date_value,
        bbox=parsed_bbox,
    )
