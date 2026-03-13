import logging

from fastapi import APIRouter, HTTPException, Query, status

from app.api.date_params import parse_api_date
from app.api.deps import ChlorophyllBreakMapServiceDep, LiveSstProviderDep, SstMapServiceDep
from app.schemas import ChlorophyllBreakMapResponse, SstMapResponse

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
    date_value: str = Query(
        alias="date",
        description="Trip date. Preferred format: YYYY-MM-DD. MM-DD-YYYY and MM/DD/YYYY are also accepted.",
    ),
    bbox: str = Query(..., description="minLng,minLat,maxLng,maxLat"),
) -> SstMapResponse:
    trip_date = parse_api_date(date_value)
    parsed_bbox = _parse_bbox(bbox)
    logger.info(
        "Handling /map/sst request",
        extra={
            "trip_date": trip_date.isoformat(),
            "bbox": list(parsed_bbox),
        },
    )
    return sst_map_service.get_sst_map(
        trip_date=trip_date,
        bbox=parsed_bbox,
    )


@router.get("/chlorophyll-breaks", response_model=ChlorophyllBreakMapResponse)
def get_chlorophyll_break_map(
    chlorophyll_break_map_service: ChlorophyllBreakMapServiceDep,
    date_value: str = Query(
        alias="date",
        description="Trip date. Preferred format: YYYY-MM-DD. MM-DD-YYYY and MM/DD/YYYY are also accepted.",
    ),
    bbox: str = Query(..., description="minLng,minLat,maxLng,maxLat"),
) -> ChlorophyllBreakMapResponse:
    trip_date = parse_api_date(date_value)
    parsed_bbox = _parse_bbox(bbox)
    logger.info(
        "Handling /map/chlorophyll-breaks request",
        extra={
            "trip_date": trip_date.isoformat(),
            "bbox": list(parsed_bbox),
        },
    )
    return chlorophyll_break_map_service.get_chlorophyll_break_map(
        trip_date=trip_date,
        bbox=parsed_bbox,
    )


@router.get("/sst/live-debug")
def get_live_sst_debug(
    live_sst_provider: LiveSstProviderDep,
    date_value: str = Query(
        alias="date",
        description="Trip date. Preferred format: YYYY-MM-DD. MM-DD-YYYY and MM/DD/YYYY are also accepted.",
    ),
    bbox: str = Query(..., description="minLng,minLat,maxLng,maxLat"),
) -> dict[str, object | None]:
    trip_date = parse_api_date(date_value)
    parsed_bbox = _parse_bbox(bbox)
    logger.info(
        "Handling /map/sst/live-debug request",
        extra={
            "trip_date": trip_date.isoformat(),
            "bbox": list(parsed_bbox),
        },
    )
    return live_sst_provider.probe_upstream_request(
        trip_date,
        min_lat=parsed_bbox[1],
        max_lat=parsed_bbox[3],
        min_lon=parsed_bbox[0],
        max_lon=parsed_bbox[2],
    )
