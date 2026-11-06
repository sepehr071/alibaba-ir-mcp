"""Where to stay: villas, suites and holiday homes (اقامتگاه) and hotels, as alibaba.ir shows them."""

from __future__ import annotations

import asyncio
import re
from datetime import date as Date
from datetime import datetime, timedelta, timezone
from typing import Annotated, Any, Literal

from pydantic import Field

from .http import ApiError, fetch
from .registry import tool
from .travel import Day, Limit, _norm, _toman, parse_day

TEHRAN = timezone(timedelta(hours=3, minutes=30))
Guests = Annotated[int, Field(description="Guests.", ge=1, le=30)]
Nights = Annotated[int, Field(description="Nights from check-in.", ge=1, le=30)]
STAY_TYPES = ("villa", "suite", "traditional", "cottage", "apartment", "hostel", "ecotourism", "complex")


def _epoch(day: Date) -> dict[str, int]:
    """The site sends dates as protobuf timestamps: local midnight in Tehran."""
    return {"seconds": int(datetime(day.year, day.month, day.day, tzinfo=TEHRAN).timestamp()), "nanos": 0}


async def stay_place(q: str) -> tuple[str, str]:
    """(page slug like city-masuleh, title) for a place name; a slug is used as given."""
    q = q.strip()
    if re.fullmatch(r"(city|province|stays|region|area)-[a-z0-9_-]+", q):
        return q, q
    found = (await fetch("v2/accommodation/Available/Suggestions", params={"Keyword": q})).get("suggestions") or []
    plp = [s for s in found if s.get("resultType") == "plp" and s.get("url")]
    if not plp:
        raise ApiError(f"No place found for '{q}'. Try a city or village name such as ماسوله, رامسر, کیش.")
    pick = next((s for s in plp if s["url"].startswith("city-")), plp[0])
    return pick["url"], pick["title"]


def _stay_row(i: dict[str, Any], nights: int) -> dict[str, Any]:
    p = i["price"]
    loc = i.get("location") or {}
    geo = loc.get("geo") or {}
    cap = i.get("capacity") or {}
    return {
        "id": i["id"],
        "name": i["name"].strip(),
        "type": i.get("type"),
        "city": loc.get("city"),
        "province": loc.get("province"),
        "guests": cap.get("base"),
        "extra_guests": cap.get("extra") or None,
        "bedrooms": (i.get("accommodationMetrics") or {}).get("bedroomsCount"),
        "area_m2": (i.get("accommodationMetrics") or {}).get("buildingSize") or None,
        "price_total_toman": _toman(p["discountedPrice"]),
        "price_per_night_toman": _toman(p["discountedPrice"] / nights),
        "price_before_discount_toman": _toman(p["mainPrice"]) if p.get("discountPercent") else None,
        "discount_percent": p.get("discountPercent") or None,
        "rating": (i.get("rateReview") or {}).get("score") or None,
        "rating_count": (i.get("rateReview") or {}).get("count") or None,
        "instant_booking": i.get("reservationType") == "instant" or i.get("isInstant") or None,
        "region": i.get("region"),
        "lat": geo.get("latitude"),
        "lon": geo.get("longitude"),
        "url": f"https://www.alibaba.ir/accommodation/pdp/{i.get('type')}-{i['code']}",
        "photo": i.get("image"),
    }


@tool("Villas and holiday homes")
async def al_stays(
    destination: Annotated[
        str,
        Field(
            description="City/village name (ماسوله, کیش) or slug like city-masuleh.",
            min_length=2,
            max_length=60,
        ),
    ],
    checkin: Day,
    nights: Nights = 1,
    guests: Guests = 2,
    type: Annotated[
        Literal["villa", "suite", "traditional", "cottage", "apartment", "hostel", "ecotourism", "complex"] | None,
        Field(description="Kind of place."),
    ] = None,
    min_price: Annotated[int | None, Field(description="Min price per night, Toman.", ge=0)] = None,
    max_price: Annotated[int | None, Field(description="Max price per night, Toman.", ge=0)] = None,
    min_rating: Annotated[float | None, Field(description="Min guest rating, 0-5.", ge=0, le=5)] = None,
    instant_only: Annotated[bool, Field(description="Only instantly bookable places.")] = False,
    sort: Annotated[
        Literal["recommended", "price", "price_desc", "rating"], Field(description="Sort order.")
    ] = "recommended",
    limit: Limit = 15,
) -> dict[str, Any]:
    """Search villas, suites, cottages and other holiday homes for rent in a city, with price, rating and capacity.

    Toman: `price_per_night_toman` is the stay average, `price_total_toman` the whole stay (no VAT). Sorting covers
    the first 100 places (`found` is the full count). al_stay_detail takes an `id`.
    """
    slug, title = await stay_place(destination)
    first = parse_day(checkin)
    last = first + timedelta(days=nights)
    filters: dict[str, Any] = {
        "isInstant": instant_only,
        "capacity": guests,
        "platform": "desktop",
        "amenities": [],
        "accommodationTypes": [type] if type else [],
        "scores": [],
        "guarantees": False,
    }
    if min_rating:
        steps = [("4.0-5.0", 4), ("3.0-4.0", 3), ("2.0-3.0", 2), ("0.0-2.0", 0)]
        filters["scores"] = [k for k, lo in steps if lo + 1 > min_rating]
    if min_price is not None or max_price is not None:
        filters["price"] = {"start": (min_price or 0) * 10, "end": (max_price or 10**9) * 10}
    data = await fetch(
        "v2/accommodation/Available/Search",
        body={
            "pageSize": 100,
            "pageNumber": 1,
            "location": slug,
            "date": {"startTime": _epoch(first), "endTime": _epoch(last)},
            "filters": filters,
        },
    )
    rows = [_stay_row(i, nights) for i in data.get("items") or [] if i["price"]["mainPrice"]]
    if min_rating:
        rows = [r for r in rows if (r["rating"] or 0) >= min_rating]
    if sort == "price":
        rows.sort(key=lambda r: r["price_per_night_toman"])
    elif sort == "price_desc":
        rows.sort(key=lambda r: -r["price_per_night_toman"])
    elif sort == "rating":
        rows.sort(key=lambda r: -(r["rating"] or 0))
    return {
        "place": title,
        "checkin": first.isoformat(),
        "nights": nights,
        "found": data.get("total"),
        "average_price_per_night_toman": _toman(data.get("avgPrice")),
        "stays": rows[:limit],
    }


@tool("Villa or holiday home details")
async def al_stay_detail(
    id: Annotated[str, Field(description="`id` from al_stays.", pattern=r"^[0-9a-f]{24}$")],
    calendar_days: Annotated[int, Field(description="Calendar days to list from today.", ge=0, le=62)] = 14,
    reviews: Annotated[int, Field(description="Recent reviews to include.", ge=0, le=10)] = 3,
) -> dict[str, Any]:
    """Show one villa or holiday home in full: capacity, beds, amenities, house rules, cancellation terms, calendar, reviews.

    Toman per night (`price_base` weekday, `price_weekend`, `price_holiday`); `calendar` gives availability and
    price per day.
    """
    got = await fetch(f"v2/accommodation/Available/GetDetails/{id}", params={"device": "desktop"})
    if not got:
        raise ApiError("That place was not found. Take an id from al_stays.")
    i = got["item"]
    meta = got.get("meta") or {}
    pr = i.get("price") or {}
    where = ((i.get("placeOfResidence") or {}).get("area") or {}).get("city") or {}
    cal = (i.get("calendar") or [])[:calendar_days]  # the site starts the list at today
    out: dict[str, Any] = {
        "id": i["id"],
        "name": i["title"],
        "type": (i.get("typeDetails") or {}).get("titleFa") or i.get("type"),
        "city": (where.get("name") or {}).get("fa"),
        "province": ((where.get("province") or {}).get("name") or {}).get("fa"),
        "description": i.get("description"),
        "check_in": i.get("checkIn"),
        "check_out": i.get("checkOut"),
        "min_nights": i.get("minNight"),
        "guests_base": (i.get("capacity") or {}).get("guests", {}).get("base"),
        "guests_max": sum((i.get("capacity") or {}).get("guests", {}).values()) or None,
        "beds": (i.get("capacity") or {}).get("beds"),
        "bedrooms": (i.get("accommodationMetrics") or {}).get("bedroomsCount"),
        "bathrooms": (i.get("accommodationMetrics") or {}).get("bathroomsCount"),
        "area_m2": (i.get("accommodationMetrics") or {}).get("buildingSize") or None,
        "price_base": _toman(pr.get("base")),
        "price_weekend": _toman(pr.get("weekend")),
        "price_holiday": _toman(pr.get("holiday")),
        "price_per_extra_guest": _toman((pr.get("extraPeople") or {}).get("base")),
        "long_stay_discount_percent": pr.get("longStaysDiscount"),
        "instant_booking": i.get("isInstant"),
        "rating": (i.get("rateAndReview") or {}).get("score"),
        "rating_count": (i.get("rateAndReview") or {}).get("count"),
        "amenities": [a["title"]["fa"] for a in i.get("amenitiesV2") or [] if a.get("state")],
        "amenity_groups": {
            g["title"]: [x["title"]["fa"] for x in g.get("items") or []] for g in i.get("amenityGroups") or []
        },
        "rules_allowed": [r["positive"] for r in i.get("restrictedRules") or []],
        "rules_forbidden": [r["negative"] for r in i.get("negativeRestrictedRules") or []],
        "cancellation": i.get("cancellationPolicyText"),
        "cancellation_policy": (i.get("cancellationPolicyDetails") or {}).get("title"),
        "calendar": [
            {
                "date": c["date"],
                "available": c["status"] == "available",
                "price_toman": _toman(c["price"]) if c["status"] == "available" else None,
            }
            for c in cal
        ],
        "url": meta.get("affiliateLink") or meta.get("link"),
    }
    if reviews:
        r = (await fetch(f"v2/accommodation/Comment/Reviews/{id}", params={"PageNumber": 1, "PageSize": reviews})) or {}
        out["rating_breakdown"] = {
            x["ratingItem"]["title"]: x["rating"] for x in r.get("items") or [] if x.get("ratingItem")
        }
        out["reviews"] = [
            {
                "date": (v.get("reviewDate") or "")[:10],
                "rating": v.get("rating"),
                "comment": v.get("comment"),
                "host_reply": (v.get("response") or {}).get("body"),
            }
            for v in (r.get("reviews") or [])[:reviews]
        ]
    return out


async def _hotel_city(q: str) -> tuple[str, str, str]:
    """(cityId, countryCode, Persian name) of the city a hotel search for `q` should use."""
    found = (await fetch("v3/hotel/suggest", params={"query": q.strip()})).get("results") or []
    cities = [x for x in found if x.get("type") == "city"]
    if not cities:
        hotel = next((x for x in found if x.get("type") == "hotel"), None)
        hint = f" '{hotel['displayName']}' is a hotel in {hotel['cityName']}: search that city." if hotel else ""
        raise ApiError(f"No hotel city found for '{q}'.{hint}")
    exact = [c for c in cities if _norm(c["displayName"]) == _norm(q)]
    c = (exact or cities)[0]
    return c["cityId"], c["countryCode"], c["displayName"]


def _hotel_row(h: dict[str, Any]) -> dict[str, Any]:
    score = h.get("score") or {}
    return {
        "name": (h.get("name") or {}).get("fa"),
        "english": (h.get("name") or {}).get("en"),
        "stars": h.get("star"),
        "rating": score.get("score") or None,
        "rating_count": score.get("count") or None,
        "price_total_toman": _toman(h.get("minPrice")),
        "price_per_night_toman": _toman(h.get("pricePerNight")),
        "price_before_discount_toman": _toman(h["oldPrice"]) if h.get("oldPrice") != h.get("minPrice") else None,
        "discount_percent": h.get("discountPercent") or None,
        "meal_plan": h.get("mealPlan"),
        "rooms": [r.get("fa") for r in (h.get("roomNames") or [])[:3]],
        "offers": [b["text"] for b in h.get("badges") or []][:4],
        "facilities": (h.get("facilitiesName") or [])[:4] or None,
        "lat": (h.get("location") or {}).get("coordinates", [None, None])[1],
        "lon": (h.get("location") or {}).get("coordinates", [None, None])[0],
        "url": f"https://www.alibaba.ir/hotel/{h['link']}" if h.get("link") else None,
    }


@tool("Hotels")
async def al_hotels(
    city: Annotated[str, Field(description="City name (مشهد, Istanbul).", min_length=2, max_length=40)],
    checkin: Day,
    nights: Nights = 1,
    adults: Annotated[int, Field(description="Adults in one room.", ge=1, le=6)] = 2,
    min_stars: Annotated[int | None, Field(description="Min stars, 1-5.", ge=1, le=5)] = None,
    sort: Annotated[Literal["rating", "price"], Field(description="Best rated or cheapest first.")] = "rating",
    only_available: Annotated[bool, Field(description="Hide hotels with no room for those dates.")] = True,
    limit: Limit = 15,
) -> dict[str, Any]:
    """Search hotels in a city for a stay: stars, rating, price for the whole stay, meal plan, perks (domestic and abroad).

    Toman for the room for all nights (`price_per_night_toman` is the average). Takes a few seconds.
    """
    city_id, country, name = await _hotel_city(city)
    first = parse_day(checkin)
    last = first + timedelta(days=nights)
    place = {"cityId": city_id, "countryCode": country}
    sess = await fetch(
        "v1/hotel/search",
        params=place,
        body={
            "checkIn": first.isoformat(),
            "checkOut": last.isoformat(),
            "destination": {"type": "City", "id": city_id},
            "rooms": [{"adults": [30] * adults, "children": []}],
        },
        fresh=True,
    )
    flt: list[dict[str, Any]] = [{"field": "onlyAvailable", "value": []}] if only_available else []
    if min_stars:
        flt.append({"field": "star", "value": list(range(min_stars, 6))})
    body = {
        "sessionId": sess["sessionId"],
        "filter": flt,
        "removeOutlier": False,
        "sort": {"order": -1, "field": "score"} if sort == "rating" else {"order": 1, "field": "minPrice"},
        "skip": 0,
        "limit": min(limit, 60),
    }
    for _ in range(10):  # hotels answer one provider at a time; progress reaches 100 when all are in
        data = await fetch("v1/hotel/result", params=place, body=body, fresh=True)
        if data.get("progress", 100) >= 100:
            break
        await asyncio.sleep(1.5)
    info = data.get("info") or {}
    return {
        "city": name,
        "checkin": first.isoformat(),
        "nights": nights,
        "adults": adults,
        "found": info.get("totalResultNo"),
        "hotels": [_hotel_row(h) for h in data.get("result") or []][:limit],
    }
