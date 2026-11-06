"""International flights (Iran to abroad and back), searched the way alibaba.ir's web app does."""

from __future__ import annotations

import asyncio
import re
from typing import Annotated, Any, Literal

from pydantic import Field

from .http import ApiError, fetch
from .registry import tool
from .travel import _DAY, Day, Limit, _sort, _toman, intl_places, parse_day

Airport = Annotated[
    str,
    Field(
        description="City/airport name (تهران, Dubai) or code (DXB, THRALL = all Tehran airports).",
        min_length=2,
        max_length=40,
    ),
]


async def _intl_code(q: str) -> str:
    """Alibaba's code for a place: an exact code, else the city's all-airports code, else the best match."""
    q = q.strip()
    places = await intl_places(q)
    if not places:
        raise ApiError(f"No airport or city found for '{q}'. Try al_cities with international=true.")
    exact = [p for p in places if p["code"].lower() == q.lower()]
    whole = [p for p in places if p["whole_city"]]
    return (exact or whole or places)[0]["code"]


def _leg(g: dict[str, Any] | None) -> dict[str, Any] | None:
    if not g:
        return None
    return {
        "airline": g.get("airlineName"),
        "from": f"{g['originCityNamePersian'] or g['originCityName']} ({g['origin']})",
        "to": f"{g['destinationCityNamePersian'] or g['destinationCityName']} ({g['destination']})",
        "departure": g["departureDateTime"],
        "arrival": g["arrivalDateTime"],
        "duration_min": g["durationMin"],
        "stops": g["numberOfStop"],
        "segments": [
            f"{s['marketingCarrier']}{s['flightNumber']} {s['origin']}-{s['destination']}" for s in g["flightDetails"]
        ],
        "baggage": g.get("lowestBaggageAmount"),
        "cabin_baggage": g.get("lowestCabinBaggageAmount"),
    }


def _proposal_row(p: dict[str, Any]) -> dict[str, Any]:
    adult = next((x for x in p.get("prices") or [] if x["paxType"] == 0), None) or (p.get("prices") or [{}])[0]
    out = _leg(p["leavingFlightGroup"])
    assert out is not None
    row = {
        **out,
        "price_toman": _toman(adult.get("perPassenger")),
        "total_toman": _toman(p.get("total")),
        "seats_left": p.get("seat"),
        "charter": p.get("isCharter") or None,
        "refundable": p.get("isRefundable"),
        "class": p["leavingFlightGroup"].get("cabinTypeName"),
        "visa": bool(p.get("visaRequirements")) or None,
    }
    if p.get("returningFlightGroup"):
        row["return"] = _leg(p["returningFlightGroup"])
    return row


async def _collect(request_id: str, tries: int = 12) -> list[dict[str, Any]]:
    """Poll the search until complete. Each poll hands out only the proposals that arrived since the last one."""
    path = f"v1/flights/international/proposal-requests/{request_id}"
    seen: dict[str, dict[str, Any]] = {}
    for _ in range(tries):
        data = await fetch(path, fresh=True)
        for p in data.get("proposals") or []:
            seen.setdefault(p["uniqueId"], p)
        if data.get("isCompleted"):
            break
        await asyncio.sleep(max(0.5, (data.get("nextRequestThreshold") or 800) / 1000))
    return list(seen.values())


@tool("International flights")
async def al_flights_international(
    origin: Airport,
    destination: Airport,
    date: Day,
    return_date: Annotated[str | None, Field(description="Round-trip return day.", pattern=_DAY)] = None,
    adults: Annotated[int, Field(description="Adults.", ge=1, le=9)] = 1,
    children: Annotated[int, Field(description="Children aged 2-11.", ge=0, le=9)] = 0,
    infants: Annotated[int, Field(description="Infants under 2.", ge=0, le=9)] = 0,
    cabin: Annotated[Literal["economy", "business", "first"], Field(description="Cabin class.")] = "economy",
    sort: Annotated[Literal["price", "departure", "duration"], Field(description="Sort order.")] = "price",
    max_stops: Annotated[int | None, Field(description="Max stops (0 = direct).", ge=0, le=3)] = None,
    airline: Annotated[str | None, Field(description="Part of an airline name, e.g. 'Turkish'.", max_length=30)] = None,
    limit: Limit = 15,
) -> dict[str, Any]:
    """Search international flights between Iran and abroad (or any two cities Alibaba sells) on one day.

    `price_toman` is per adult, `total_toman` for the whole group. With return_date each fare has a `return` leg.
    Codes: al_cities with international=true. Takes 10-20 seconds.
    """
    day = parse_day(date)
    back = parse_day(return_date) if return_date else None
    if back and back < day:
        raise ApiError("return_date is before date.")
    if infants > adults:
        raise ApiError("Each infant needs an adult: infants cannot be more than adults.")
    o, d = await _intl_code(origin), await _intl_code(destination)
    start = await fetch(
        "v1/flights/international/proposal-requests",
        body={
            "infant": infants,
            "child": children,
            "adult": adults,
            "departureDate": day.isoformat(),
            "origin": o,
            "destination": d,
            "flightClass": cabin.capitalize(),
            **({"returnDate": back.isoformat()} if back else {}),
        },
        fresh=True,
    )
    rows = [_proposal_row(p) for p in await _collect(start["requestId"])]
    total = len(rows)
    if max_stops is not None:
        rows = [r for r in rows if r["stops"] <= max_stops]
    if airline:
        want = re.sub(r"\s+", "", airline).lower()
        rows = [r for r in rows if want in re.sub(r"\s+", "", r["airline"] or "").lower()]
    return {
        "from": o,
        "to": d,
        "date": day.isoformat(),
        "return_date": back and back.isoformat(),
        "region": start.get("regionType"),
        "found": total,
        "flights": _sort(rows, sort)[:limit],
    }
