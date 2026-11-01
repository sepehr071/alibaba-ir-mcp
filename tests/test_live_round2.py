from datetime import date, timedelta

import pytest

pytestmark = [pytest.mark.live, pytest.mark.anyio]

DAY = (date.today() + timedelta(days=10)).isoformat()
BACK = (date.today() + timedelta(days=14)).isoformat()


async def test_live_cities_international(client):
    r = (await client.call_tool("al_cities", {"query": "Istanbul", "international": True})).structured_content
    assert any(p["code"] == "ISTALL" for p in r["places"]), r


async def test_live_flights_international_round_trip(client):
    r = (
        await client.call_tool(
            "al_flights_international",
            {"origin": "تهران", "destination": "Istanbul", "date": DAY, "return_date": BACK, "limit": 5},
        )
    ).structured_content
    assert r["found"] > 0 and r["flights"][0]["price_toman"] > 1_000_000 and r["flights"][0]["return"], r


async def test_live_flights_domestic_round_trip_with_rules(client):
    r = (
        await client.call_tool(
            "al_flights",
            {"origin": "THR", "destination": "MHD", "date": DAY, "return_date": BACK, "refund_rules": True, "limit": 3},
        )
    ).structured_content
    assert r["flights"] and r["returning"] and r["flights"][0]["refund_penalties"], r


async def test_live_buses_cheapest_and_seats(client):
    r = (
        await client.call_tool(
            "al_buses_cheapest", {"origin": "تهران", "destination": "اصفهان", "date": DAY, "days": 2}
        )
    ).structured_content
    assert r["cheapest"]["price_toman"] > 100_000, r
    b = (
        await client.call_tool("al_buses", {"origin": "تهران", "destination": "اصفهان", "date": DAY, "limit": 1})
    ).structured_content["buses"][0]
    seats = await client.call_tool(
        "al_bus_seats",
        {
            "origin": "تهران",
            "destination": "اصفهان",
            "date": DAY,
            "departure_time": b["departure"][11:16],
            "company": b["company"][:12],
        },
    )
    assert seats.is_error or seats.structured_content["seats_total"] > 5, seats.content[0].text


async def test_live_trains_round_trip_or_site_maintenance(client):
    r = await client.call_tool(
        "al_trains", {"origin": "THR", "destination": "MHD", "date": DAY, "return_date": BACK, "limit": 3}
    )
    if r.is_error:
        assert "ریلی" in r.content[0].text, r.content[0].text
    else:
        assert r.structured_content["trains"] and r.structured_content["returning"]


async def test_live_stays_and_detail(client):
    r = (
        await client.call_tool(
            "al_stays",
            {
                "destination": "ماسوله",
                "checkin": DAY,
                "nights": 2,
                "guests": 4,
                "type": "villa",
                "sort": "price",
                "limit": 3,
            },
        )
    ).structured_content
    assert r["found"] > 0 and r["stays"][0]["price_per_night_toman"] > 100_000, r
    d = (
        await client.call_tool("al_stay_detail", {"id": r["stays"][0]["id"], "calendar_days": 5, "reviews": 1})
    ).structured_content
    assert d["name"] and d["calendar"] and d["cancellation"], d


async def test_live_hotels(client):
    r = (
        await client.call_tool("al_hotels", {"city": "مشهد", "checkin": DAY, "nights": 2, "adults": 1, "limit": 3})
    ).structured_content
    assert r["found"] > 0 and r["hotels"][0]["price_total_toman"] > 100_000, r


async def test_live_tours(client):
    r = (
        await client.call_tool("al_tours", {"destination": "کیش", "checkin": DAY, "nights": 3, "limit": 3})
    ).structured_content
    assert r["found"] > 0 and r["tours"][0]["price_per_person_toman"] > 100_000, r


async def test_live_tours_cheapest(client):
    r = (
        await client.call_tool("al_tours_cheapest", {"destination": "کیش", "checkin": DAY, "nights": 3})
    ).structured_content
    assert r["days"] and r["cheapest"]["price_per_person_toman"] > 100_000, r
