"""Tour packages (flight or bus plus hotel) as alibaba.ir's tour pages show them."""

from __future__ import annotations

import asyncio
from datetime import timedelta
from typing import Annotated, Any, Literal

from pydantic import Field

from .http import ApiError, fetch
from .lodging import Nights
from .registry import tool
from .travel import Day, Limit, _clean, _norm, _toman, parse_day


def _places(groups: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [p for g in groups for p in g.get("places") or []]


def _names(p: dict[str, Any]) -> list[str]:
    return [_norm(p["name"]), _norm(p["domainCode"])] + [_norm(n["value"]) for n in p.get("displayName") or []]


async def _tour_place(kind: Literal["sources", "all-destinations"], q: str, what: str) -> dict[str, Any]:
    places = _places(await fetch(f"v1/tour/available-api/available/{kind}"))
    n = _norm(q)
    exact = [p for p in places if n in _names(p)]
    hits = exact or [p for p in places if any(n in x for x in _names(p))]
    if len(hits) == 1 or exact:
        return (exact or hits)[0]
    names = ", ".join(p["name"] for p in hits[:10]) or ", ".join(p["name"] for p in places if p.get("isPopular"))
    raise ApiError(f"No unique tour {what} for '{q}'. {'Did you mean' if hits else 'Popular ones'}: {names}.")


@tool("Tour packages")
async def al_tours(
    destination: Annotated[
        str,
        Field(
            description="Destination city in Persian or English: کیش, Mashhad, استانبول, Dubai.",
            min_length=2,
            max_length=40,
        ),
    ],
    checkin: Day,
    nights: Nights = 3,
    origin: Annotated[
        str,
        Field(description="Departure city, tours start from Tehran, Isfahan, Mashhad and a few more.", max_length=40),
    ] = "تهران",
    adults: Annotated[
        int, Field(description="Travellers sharing one room (the price is for the whole group).", ge=1, le=4)
    ] = 2,
    min_stars: Annotated[int | None, Field(description="Lowest hotel star rating to keep, 1-5.", ge=1, le=5)] = None,
    max_price: Annotated[int | None, Field(description="Highest price per person in Toman.", ge=0)] = None,
    sort: Annotated[Literal["price", "rating", "stars"], Field(description="Order of the results.")] = "price",
    limit: Limit = 15,
) -> dict[str, Any]:
    """Search tour packages (round trip plus hotel) from a city to a destination such as Kish, Mashhad, Istanbul or Dubai.

    Use for "a 3-night Kish tour for two from Tehran next week". Each result is a hotel with the cheapest package:
    hotel, stars, rating, room, meal plan, how you travel, and the price per person and for the whole group in
    Toman. Results come in after a few seconds (at most 15 polls per call). To buy, send the user to alibaba.ir.
    """
    dest = await _tour_place("all-destinations", destination, "destination")
    org = await _tour_place("sources", origin, "origin")
    first = parse_day(checkin)
    last = first + timedelta(days=nights)
    start = await fetch(
        "v1/tour/available-api/available/plp-chunksearch",
        params={
            "origin": org["domainCode"],
            "destination": dest["domainCode"],
            "from": first.isoformat(),
            "to": last.isoformat(),
            "rooms": adults,
        },
        fresh=True,
    )
    key = start["availableSearch"]["searchKey"]
    for _ in range(15):  # suppliers answer one by one; isFinished marks the last batch
        data = await fetch("v3/tour/available-api/available/plp-result", params={"searchKey": key}, fresh=True)
        if data.get("isFinished"):
            break
        await asyncio.sleep(1.5)
    if (data.get("error") or {}).get("errorCode"):
        raise ApiError(data["error"].get("errorMessage") or "The tour search failed. Try other dates.")
    rows = [_tour_row(t) for t in data.get("plpItems") or []]
    if min_stars:
        rows = [r for r in rows if (r["stars"] or 0) >= min_stars]
    if max_price:
        rows = [r for r in rows if r["price_per_person_toman"] <= max_price]
    order = {
        "price": lambda r: r["price_per_person_toman"],
        "rating": lambda r: -(r["rating"] or 0),
        "stars": lambda r: -(r["stars"] or 0),
    }[sort]
    rows.sort(key=order)
    return {
        "from": org["name"],
        "to": dest["name"],
        "checkin": first.isoformat(),
        "checkout": last.isoformat(),
        "adults": adults,
        "found": data.get("totalResultCount"),
        "tours": rows[:limit],
    }


@tool("Cheapest tour per day")
async def al_tours_cheapest(
    destination: Annotated[
        str,
        Field(
            description="Destination city in Persian or English: کیش, Mashhad, استانبول, Dubai.",
            min_length=2,
            max_length=40,
        ),
    ],
    checkin: Day,
    nights: Nights = 3,
    origin: Annotated[
        str, Field(description="Departure city (Tehran, Isfahan, Mashhad and a few more).", max_length=40)
    ] = "تهران",
) -> dict[str, Any]:
    """List the lowest tour price per person for 11 departure days around a date (5 before, 5 after), to pick the cheapest day.

    Use before al_tours when the date is flexible. Prices are Toman per person for a tour of `nights` nights; a day
    without tours is missing. Then call al_tours for the chosen day.
    """
    dest = await _tour_place("all-destinations", destination, "destination")
    org = await _tour_place("sources", origin, "origin")
    first = parse_day(checkin)
    last = first + timedelta(days=nights)
    data = await fetch(
        f"v1/tour/available-api/available/timetable/{org['domainCode']}/{dest['domainCode']}/{first.isoformat()}/{last.isoformat()}"
    )
    days = [
        {
            "checkin": x["checkin"][:10],
            "checkout": x["checkout"][:10],
            "price_per_person_toman": _toman(x["personPrice"]),
        }
        for x in data.get("timeTableCalendarMinPriceItems") or []
        if x.get("hasAnyAvailableItem") and x.get("personPrice")
    ]
    return {
        "from": org["name"],
        "to": dest["name"],
        "nights": nights,
        "days": days,
        "cheapest": min(days, key=lambda r: r["price_per_person_toman"], default=None),
    }


def _tour_row(t: dict[str, Any]) -> dict[str, Any]:
    h = (t.get("hotels") or [{}])[0]
    sel = t.get("selectedAccommodations") or {}
    room = (sel.get("rooms") or [{}])[0]
    return {
        "hotel": h.get("name"),
        "english": h.get("englishName") or None,
        "kind": h.get("category"),
        "stars": h.get("star") or None,
        "rating": h.get("score") or None,
        "rating_count": h.get("totalReviewsCount") or None,
        "price_per_person_toman": _toman(t["personPrice"]),
        "price_total_toman": _toman(t["totalPrice"]),
        "price_before_discount_toman": _toman(t["previousTotalPrice"]) if t.get("previousTotalPrice") else None,
        "room": _clean(room.get("name") or "") or None,
        "meal_plan": room.get("board"),
        "transport": [x["transportationTypeTitle"] for x in sel.get("transportationTypes") or []],
        "address": _clean(h.get("address") or "") or None,
        "lat_lon": h.get("map") or None,
    }
