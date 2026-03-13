from __future__ import annotations

from datetime import date, datetime

from fastapi import HTTPException, status


def parse_api_date(date_value: str) -> date:
    normalized = date_value.strip()
    for candidate_format in ("%Y-%m-%d", "%m-%d-%Y", "%m/%d/%Y"):
        try:
            return datetime.strptime(normalized, candidate_format).date()
        except ValueError:
            continue

    raise HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        detail=(
            "Invalid date format. Use YYYY-MM-DD, MM-DD-YYYY, or MM/DD/YYYY."
        ),
    )
