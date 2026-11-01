"""Alibaba tools: city codes, trains, buses and domestic flights (search and cheapest-day calendars)."""

from __future__ import annotations

import asyncio
import json
import re
from datetime import date, datetime, timedelta
from importlib import resources
from typing import Annotated, Any, Literal

from pydantic import Field

from .http import ApiError, fetch
from .registry import tool

Place = Annotated[
    str,
    Field(
        description="City name in Persian or English (تهران, Mashhad) or its code (THR, MHD); al_cities lists them.",
        min_length=2,
        max_length=40,
    ),
]
_DAY = r"^\d{4}[-/]\d{1,2}[-/]\d{1,2}$"
Day = Annotated[
    str,
    Field(description="Travel date, Gregorian 2026-11-11 or Jalali 1405-08-20 (the year tells which).", pattern=_DAY),
]
Limit = Annotated[int, Field(description="Maximum number of results.", ge=1, le=60)]


def _load(name: str) -> list[list[str]]:
    return json.loads(resources.files(__package__).joinpath(name).read_text(encoding="utf-8"))


TRAIN_CITIES = _load("train_cities.json")  # [code, fa, en, train id]; also the cities buses are sold for
AIRPORTS = _load("airports.json")  # [code, fa, en]; Alibaba's list of domestic airports
_EN = {a[0]: a[2] for a in AIRPORTS}
for _r in TRAIN_CITIES:  # the train list only has the code as its English name
    _r[2] = _EN.get(_r[0], _r[2])


def jalali_to_gregorian(jy: int, jm: int, jd: int) -> date:
    jy += 1595
    days = -355668 + 365 * jy + (jy // 33) * 8 + ((jy % 33) + 3) // 4 + jd
    days += (jm - 1) * 31 if jm < 7 else (jm - 7) * 30 + 186
    gy = 400 * (days // 146097)
    days %= 146097
    if days > 36524:
        days -= 1
        gy += 100 * (days // 36524)
        days %= 36524
        if days >= 365:
            days += 1
    gy += 4 * (days // 1461)
    days %= 1461
    if days > 365:
        gy += (days - 1) // 365
        days = (days - 1) % 365
    gd = days + 1
    leap = gy % 4 == 0 and gy % 100 != 0 or gy % 400 == 0
    month_len = [0, 31, 29 if leap else 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]
    gm = 0
    while gm < 13 and gd > month_len[gm]:
        gd -= month_len[gm]
        gm += 1
    return date(gy, gm, gd)


def parse_day(text: str) -> date:
    y, m, d = (int(x) for x in re.split(r"[-/]", text))
    try:
        return jalali_to_gregorian(y, m, d) if y < 1700 else date(y, m, d)
    except ValueError as e:
        raise ApiError(f"'{text}' is not a valid date. Use 2026-11-11 or 1405-08-20.") from e


def _norm(s: str) -> str:
    return s.replace("ي", "ی").replace("ك", "ک").replace("\u200c", " ").strip().lower()


def find_place(rows: list[list[str]], q: str, what: str) -> list[str]:
    """One row of `rows` ([code, fa, en, ...]) whose code or name matches `q`, else an error listing near matches."""
    n = _norm(q)
    exact = [r for r in rows if n in (r[0].lower(), _norm(r[1]), _norm(r[2]))]
    hits = exact or [r for r in rows if n in _norm(r[1]) or n in _norm(r[2])]
    if len(hits) == 1 or exact:
        return (exact or hits)[0]
    names = ", ".join(f"{r[1]} ({r[0]})" for r in hits[:8])
    raise ApiError(f"No unique {what} for '{q}'." + (f" Did you mean: {names}?" if hits else " Try al_cities."))


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _toman(rial: float | int | None) -> int | None:
    return None if rial is None else round(rial / 10)


def _hhmm(iso: str) -> str:
    return iso[11:16]


def _minutes(a: str, b: str) -> int:
    return round((datetime.fromisoformat(b) - datetime.fromisoformat(a)).total_seconds() / 60)


def _sort(rows: list[dict[str, Any]], sort: str) -> list[dict[str, Any]]:
    key = {"price": "price_toman", "departure": "departure", "duration": "duration_min"}[sort]
    return sorted(rows, key=lambda r: (r.get(key) is None, r.get(key)))


def _intl_name(names: list[dict[str, str]] | None, fallback: str) -> str:
    return next((n["value"] for n in names or [] if n.get("language") == "fa-IR"), fallback)


async def intl_places(query: str) -> list[dict[str, Any]]:
    """Airports and cities Alibaba sells international flights for, matching a Persian/English name or code."""
    items = (await fetch("v1/basic-info/airports/international", params={"filter": f"q={{ct:'{query}'}}"})).get("items")
    return [
        {
            "code": i["domainCode"],
            "name": _intl_name(i.get("displayName"), i["name"]),
            "english": i["name"],
            "city": _intl_name(i["city"].get("displayName"), i["city"]["name"]),
            "country": _intl_name(i["city"]["country"].get("displayName"), i["city"]["country"]["name"]),
            "whole_city": i["domainCode"].endswith("ALL"),
        }
        for i in items or []
    ]


@tool("City and airport codes")
async def al_cities(
    query: Annotated[
        str, Field(description="Part of a city name in Persian or English, or a code. Empty lists all.", max_length=40)
    ] = "",
    limit: Limit = 30,
    international: Annotated[
        bool,
        Field(
            description="Look up airports and cities worldwide for al_flights_international instead of Iranian cities."
        ),
    ] = False,
) -> dict[str, Any]:
    """Look up the city codes the other tools take (THR for Tehran, MHD for Mashhad) and what is sold for each city.

    Use first when the user names a city: pass the returned `code` to al_trains, al_buses or al_flights.
    `train` is true for cities with a station, `flight` for cities with a domestic airport. Buses use the same
    codes (a tiny train stop may have no buses). With international=true it searches the whole world (Dubai,
    Istanbul, Paris) and returns airports; `whole_city` rows (code ending in ALL) cover every airport of a city.
    """
    if international:
        if not query.strip():
            raise ApiError("Give a city or airport name to search worldwide, for example 'Dubai' or 'استانبول'.")
        rows = await intl_places(query.strip())
        return {"count": len(rows), "places": rows[:limit]}
    n = _norm(query)
    merged: dict[str, dict[str, Any]] = {}
    for code, fa, *_ in TRAIN_CITIES:
        merged[code] = {"code": code, "name": fa, "train": True, "flight": False}
    for code, fa, en in AIRPORTS:
        row = merged.setdefault(code, {"code": code, "name": fa, "train": False})
        row["english"], row["flight"] = en, True
    rows = [
        r
        for r in merged.values()
        if not n or n in _norm(r["name"]) or n in _norm(r.get("english", "")) or n == r["code"].lower()
    ]
    return {"count": len(rows), "cities": rows[:limit]}


@tool("Train tickets")
async def al_trains(
    origin: Place,
    destination: Place,
    date: Day,
    sort: Annotated[
        Literal["price", "departure", "duration"], Field(description="Order of the results.")
    ] = "departure",
    only_available: Annotated[bool, Field(description="Hide sold-out trains.")] = True,
    limit: Limit = 25,
    return_date: Annotated[
        str | None,
        Field(
            description="Return day for a round trip (same formats as `date`); adds a `returning` list.", pattern=_DAY
        ),
    ] = None,
    passengers: Annotated[
        int, Field(description="Number of travellers; seats_left is for this group size.", ge=1, le=9)
    ] = 1,
    ticket_type: Annotated[
        Literal["family", "female", "male"],
        Field(
            description="family = mixed compartments; female or male = single-gender compartments (seat counts differ)."
        ),
    ] = "family",
    wagon_class: Annotated[
        str | None,
        Field(
            description="Keep only this class code from the results, e.g. EC (compartment), EL (6-berth), S (saloon), V.",
            max_length=3,
        ),
    ] = None,
) -> dict[str, Any]:
    """Search train tickets between two Iranian cities on one day: company, class, times, price and seats left.

    Use for "trains from Tehran to Mashhad on 1405-08-20". Prices are Toman per adult. `seats_left` 0 means sold out.
    `class` is the wagon name (stars, berths, meals) and `class_code` its type: S saloon seats, EC 4-berth
    compartment, EL 6-berth compartment, V special. Pass return_date for the way back. Call al_trains_cheapest to
    compare prices over the following days. While the rail suppliers are in their maintenance window (usually
    after midnight) the site answers with an error; try again in a few minutes.
    """
    o = find_place(TRAIN_CITIES, origin, "train city")
    d = find_place(TRAIN_CITIES, destination, "train city")
    day = parse_day(date)
    back = parse_day(return_date) if return_date else None
    if back and back < day:
        raise ApiError("return_date is before date.")
    start = await fetch(
        "v2/train/available",
        body={
            "departureDate": day.isoformat(),
            "origin": o[0],
            "destination": d[0],
            "passengerCount": passengers,
            "isExclusiveCompartment": False,
            "ticketType": ticket_type.capitalize(),
            **({"returnDate": back.isoformat()} if back else {}),
        },
    )
    data = await _poll(f"v2/train/available/{start['requestId']}")
    out = {"from": o[1], "to": d[1], "date": day.isoformat()}
    for key, field in (("trains", "departing"), ("returning", "returning")):
        rows = [_train_row(t) for t in data.get(field) or []]
        if wagon_class:
            rows = [r for r in rows if r["class_code"] == wagon_class.upper()]
        total = len(rows)
        if only_available:
            rows = [r for r in rows if r["seats_left"] > 0]
        if key == "trains":
            out.update(found=total, available=len(rows))
        elif not back:
            continue
        out[key] = _sort(rows, sort)[:limit]
    if back:
        out["return_date"] = back.isoformat()
    return out


def _train_row(t: dict[str, Any]) -> dict[str, Any]:
    dep, arr = t["departureDateTime"], t["arrivalDateTime"]
    return {
        "train": t["trainNumber"],
        "company": _clean(t["companyName"]),
        "class": _clean(t["wagonName"]),
        "class_code": t.get("wagonClass"),
        "departure": dep,
        "arrival": arr,
        "duration_min": _minutes(dep, arr),
        "price_toman": _toman(t["cost"]),
        "full_price_toman": _toman(t["fullPrice"]) if t.get("fullPrice") and t["fullPrice"] != t["cost"] else None,
        "discount": (t.get("specialOfferTexts") or [None])[0],
        "seats_left": t["seat"],
        "compartment": f"{t['compartmentCapacity']} berths" if t.get("isCompartment") else None,
        "family_coupe": t.get("isFamilyCoupe") or None,
        "max_passengers": t.get("maxPassengerCount"),
        "air_conditioning": t.get("hasAirCondition"),
        "media": t.get("hasMedia"),
        "free_food": t.get("hasFreeFood") or None,
        "food_offer": (t.get("foodOfferTexts") or [None])[0],
        "refundable": not t.get("nonRefundable"),
        "charter": t.get("isCharter") or None,
    }


@tool("Cheapest train per day")
async def al_trains_cheapest(
    origin: Place,
    destination: Place,
    date: Day,
    days: Annotated[int, Field(description="How many days to list, starting at `date`.", ge=1, le=15)] = 7,
) -> dict[str, Any]:
    """List the lowest train price for each day from a start date, to pick the cheapest day to travel.

    Use before al_trains when the date is flexible. Prices are Toman per adult; a missing day has no train.
    """
    o = find_place(TRAIN_CITIES, origin, "train city")
    d = find_place(TRAIN_CITIES, destination, "train city")
    day = parse_day(date)
    rows = await fetch(
        "v2/train/available/cheapest",
        body={"origin": o[0], "destination": d[0], "ticketType": "Family", "fromDate": day.isoformat()},
    )
    out = [{"date": r["departureDateTime"][:10], "price_toman": _toman(r["adultPrice"])} for r in rows[:days]]
    return {"from": o[1], "to": d[1], "days": out, "cheapest": min(out, key=lambda r: r["price_toman"], default=None)}


async def bus_city_code(place: str) -> tuple[str, str]:
    """(Alibaba's 8-digit city code, Persian name) for a bus city."""
    city = find_place(TRAIN_CITIES, place, "bus city")
    items = (await fetch("v1/bus/stations", params={"filter": f"q={{ct:'{city[0]}'}}"})).get("items") or []
    if not items:
        raise ApiError(f"Alibaba sells no bus tickets for {city[1]}.")
    return items[0]["domainCode"], items[0]["name"]


@tool("Bus tickets")
async def al_buses(
    origin: Place,
    destination: Place,
    date: Day,
    sort: Annotated[Literal["price", "departure"], Field(description="Order of the results.")] = "departure",
    only_available: Annotated[bool, Field(description="Hide buses with no free seat.")] = True,
    limit: Limit = 25,
) -> dict[str, Any]:
    """Search intercity bus tickets between two Iranian cities on one day: company, bus type, times, price, seats.

    Use for "buses from Tehran to Shiraz tomorrow". Prices are Toman per adult. `from_terminal` is the terminal of
    that departure (Tehran has several). Bus tickets carry no arrival time on the site.
    """
    (oc, oname), (dc, dname) = await bus_city_code(origin), await bus_city_code(destination)
    day = parse_day(date)
    data = await _bus_search(oc, dc, day)
    rows = [_bus_row(b) for b in data.get("availableList") or []]
    total = len(rows)
    if only_available:
        rows = [r for r in rows if r["seats_left"] > 0]
    out = {"from": oname, "to": dname, "date": day.isoformat(), "found": total, "buses": _sort(rows, sort)[:limit]}
    if not total:
        out["route_status"] = data.get("routeAvailability")  # e.g. TemporarilyUnavailable: no buses sold on that date
        out["next_available_date"] = (data.get("firstNextAvailableDate") or "")[:10] or None
        out["next_available_price_toman"] = _toman(data.get("firstNextAvailablePrice")) or None
    return out


async def _bus_search(oc: str, dc: str, day: date) -> dict[str, Any]:
    return await fetch(
        "v2/bus/available",
        params={
            "orginCityCode": oc,
            "destinationCityCode": dc,
            "requestDate": day.isoformat(),
            "passengerCount": 1,
            "serviceType": "Bus",
        },
    )


def _bus_row(b: dict[str, Any]) -> dict[str, Any]:
    return {
        "company": _clean(b["companyName"]),
        "bus_type": _clean(b["busType"]),
        "departure": b["departureDateTime"],
        "price_toman": _toman(b["price"]),
        "price_before_discount_toman": _toman(b["beforeDiscountPrice"])
        if b.get("beforeDiscountPrice") != b["price"]
        else None,
        "seats_left": b["availableSeats"],
        "from_terminal": b.get("orginTerminal"),
        "to_terminal": b.get("destinationTerminal"),
        "stops": b.get("droppingPoints"),
        "rating": b.get("rate"),
        "rating_count": b.get("rateCount") or None,
        "refundable": b.get("isRefundable"),
        "charter": b.get("isCharter") or None,
    }


@tool("Cheapest bus per day")
async def al_buses_cheapest(
    origin: Place,
    destination: Place,
    date: Day,
    days: Annotated[int, Field(description="How many days to check, starting at `date`.", ge=1, le=10)] = 5,
) -> dict[str, Any]:
    """List the lowest bus price and the number of buses for each day from a start date (the site has no bus calendar).

    Use before al_buses when the date is flexible. It runs one search per day, so keep `days` small. Prices are
    Toman per adult for buses with a free seat; a day with none shows no price.
    """
    (oc, oname), (dc, dname) = await bus_city_code(origin), await bus_city_code(destination)
    first = parse_day(date)
    out = []
    for i in range(days):
        day = first + timedelta(days=i)
        rows = [_bus_row(b) for b in (await _bus_search(oc, dc, day)).get("availableList") or []]
        free = [r for r in rows if r["seats_left"] > 0]
        cheapest = min(free, key=lambda r: r["price_toman"], default=None)
        out.append(
            {
                "date": day.isoformat(),
                "buses": len(free),
                "price_toman": cheapest and cheapest["price_toman"],
                "departure": cheapest and cheapest["departure"][11:16],
            }
        )
    priced = [r for r in out if r["price_toman"]]
    return {
        "from": oname,
        "to": dname,
        "days": out,
        "cheapest": min(priced, key=lambda r: r["price_toman"], default=None),
    }


@tool("Bus seat map")
async def al_bus_seats(
    origin: Place,
    destination: Place,
    date: Day,
    departure_time: Annotated[
        str, Field(description="Departure time of the bus from al_buses, HH:MM.", pattern=r"^\d{1,2}:\d{2}$")
    ],
    company: Annotated[
        str | None,
        Field(
            description="Part of the company name, to pick one when several buses leave at that time.", max_length=40
        ),
    ] = None,
) -> dict[str, Any]:
    """Show which seats are free on one bus: counts per status and the free seat numbers (no booking).

    Use after al_buses when the user cares where they sit or asks how full a bus is. Pick the bus by its departure
    time (and company). `layout` gives each seat's row and column (columns 1-2 left of the aisle, 4-5 right) so
    pairs can be found; statuses mean Available, booked for a male or female passenger, or Blocked (not for sale).
    """
    (oc, oname), (dc, dname) = await bus_city_code(origin), await bus_city_code(destination)
    day = parse_day(date)
    hh, mm = departure_time.split(":")
    want = f"{int(hh):02d}:{mm}"
    cands = [
        b
        for b in (await _bus_search(oc, dc, day)).get("availableList") or []
        if b["departureDateTime"][11:16] == want and (not company or _norm(company) in _norm(b["companyName"]))
    ]
    if not cands:
        raise ApiError(f"No bus leaves {oname} for {dname} at {want} on {day.isoformat()}. Call al_buses first.")
    if len(cands) > 1:
        names = ", ".join(sorted({_clean(b["companyName"]) for b in cands}))
        raise ApiError(f"{len(cands)} buses leave at {want}; add `company` (one of: {names}).")
    b = cands[0]
    seats = await fetch(
        "v1/bus/available/seats",
        body={"proposalId": b["proposalId"], "uniqueServiceToken": b["uniqueServiceToken"], "passengerCount": 1},
    )
    counts: dict[str, int] = {}
    for s in seats:
        counts[s["status"]] = counts.get(s["status"], 0) + 1
    return {
        "company": _clean(b["companyName"]),
        "bus_type": _clean(b["busType"]),
        "departure": b["departureDateTime"],
        "price_toman": _toman(b["price"]),
        "seats_total": len(seats),
        "status_counts": counts,
        "free_seats": [s["number"] for s in seats if s["status"] == "Available"],
        "layout": {s["number"]: f"r{s['row']}c{s['column']}" for s in seats if s["status"] == "Available"},
    }


@tool("Domestic flights")
async def al_flights(
    origin: Place,
    destination: Place,
    date: Day,
    sort: Annotated[Literal["price", "departure"], Field(description="Order of the results.")] = "departure",
    only_available: Annotated[bool, Field(description="Hide fares with no seat left.")] = True,
    limit: Limit = 25,
    return_date: Annotated[
        str | None,
        Field(
            description="Return day for a round trip (same formats as `date`); adds a `returning` list.", pattern=_DAY
        ),
    ] = None,
    adults: Annotated[int, Field(description="Number of adults.", ge=1, le=9)] = 1,
    children: Annotated[int, Field(description="Number of children (2-11); their fare is lower.", ge=0, le=9)] = 0,
    infants: Annotated[int, Field(description="Number of infants under 2 (one per adult at most).", ge=0, le=9)] = 0,
    refund_rules: Annotated[
        bool, Field(description="Add `refund_penalties` (cancellation fee by time before departure) to each fare.")
    ] = False,
) -> dict[str, Any]:
    """Search domestic flights between two Iranian airports on one day: airline, flight number, times, fare, seats.

    Use for "flights from Tehran to Shiraz on 2026-11-12". Prices are Toman per adult (`child_price_toman` and
    `infant_price_toman` for the others); one flight can appear several times with different fare classes. Pass
    return_date for a round trip, refund_rules for the cancellation fee table, adults/children/infants for a
    group. For other days call al_flights_cheapest first. For flights abroad use al_flights_international.
    """
    o = find_place(AIRPORTS, origin, "airport city")
    d = find_place(AIRPORTS, destination, "airport city")
    day = parse_day(date)
    back = parse_day(return_date) if return_date else None
    if back and back < day:
        raise ApiError("return_date is before date.")
    if infants > adults:
        raise ApiError("Each infant needs an adult: infants cannot be more than adults.")
    start = await fetch(
        "v1/flights/domestic/available",
        body={
            "origin": o[0].lower(),
            "destination": d[0].lower(),
            "departureDate": day.isoformat(),
            "adult": adults,
            "child": children,
            "infant": infants,
            **({"returnDate": back.isoformat()} if back else {}),
        },
    )
    data = await _poll(f"v1/flights/domestic/available/{start['requestId']}")
    out = {"from": o[1], "to": d[1], "date": day.isoformat()}
    for key, field in (("flights", "departing"), ("returning", "returning")):
        if key == "returning" and not back:
            break
        rows = [_flight_row(f, refund_rules) for f in data.get(field) or []]
        total = len(rows)
        if only_available:
            rows = [r for r in rows if r["seats_left"] > 0]
        if key == "flights":
            out["found"] = total
        out[key] = _sort(rows, sort)[:limit]
    if back:
        out["return_date"] = back.isoformat()
    return out


def _flight_row(f: dict[str, Any], refund_rules: bool) -> dict[str, Any]:
    row = {
        "airline": f["airlineName"],
        "airline_code": f["airlineCode"],
        "flight": f["airlineCode"] + f["flightNumber"],
        "departure": f["leaveDateTime"],
        "arrival": f["arrivalDateTime"],
        "aircraft": (f.get("aircraft") or "").strip() or None,
        "fare_class": f.get("classTypeName"),
        "price_toman": _toman(f["priceAdult"]),
        "child_price_toman": _toman(f.get("priceChild")),
        "infant_price_toman": _toman(f.get("priceInfant")),
        "seats_left": f["seat"],
        "baggage_kg": f.get("maxAllowedBaggage"),
        "refundable": f.get("isRefundable"),
        "charter": f.get("isCharter") or None,
        "terminal": f.get("terminal"),
    }
    if refund_rules and f.get("crcn"):
        row["refund_penalties"] = f["crcn"]  # {"until 3 days before departure": "40%", ...}, the share of the fare lost
    return row


@tool("Cheapest flight per day")
async def al_flights_cheapest(
    origin: Place,
    destination: Place,
    date: Day,
    days: Annotated[int, Field(description="How many days to list, starting at `date`.", ge=1, le=15)] = 7,
) -> dict[str, Any]:
    """List the lowest domestic fare for each day from a start date, to pick the cheapest day to fly.

    Use before al_flights when the date is flexible. Prices are Toman per adult; a day with no flight is missing.
    """
    o = find_place(AIRPORTS, origin, "airport city")
    d = find_place(AIRPORTS, destination, "airport city")
    day = parse_day(date)
    rows = await fetch(
        "v2/flights/domestic/available/cheapest",
        body={
            "referenceDate": day.isoformat(),
            "forwardDay": days - 1,
            "backwardDay": 0,
            "origin": o[0].lower(),
            "destination": d[0].lower(),
        },
    )
    out = [
        {
            "date": r["departureDateTime"][:10],
            "price_toman": _toman(r["adultPrice"]),
            "airline_code": r["airline"],
            "departure": _hhmm(r["departureDateTime"]),
            "seats_left": r["capacity"],
        }
        for r in rows
    ]
    return {"from": o[1], "to": d[1], "days": out, "cheapest": min(out, key=lambda r: r["price_toman"], default=None)}


async def _poll(path: str, tries: int = 5) -> dict[str, Any]:
    """GET a search result until the site marks it complete (providers answer one by one)."""
    for i in range(tries):
        data = await fetch(path)
        if data.get("isCompleted") or i == tries - 1:
            return data
        _forget(path)
        await asyncio.sleep(1.5)
    return data  # pragma: no cover


def _forget(path: str) -> None:
    """Drop the cached partial answer so the next poll asks the site again."""
    from . import http

    for k in [k for k in http._cache if k[0].endswith(path)]:
        del http._cache[k]
