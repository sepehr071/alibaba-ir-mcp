from datetime import date, timedelta

import pytest

pytestmark = [pytest.mark.live, pytest.mark.anyio]

DAY = (date.today() + timedelta(days=10)).isoformat()


async def test_live_cities(client):
    r = (await client.call_tool("al_cities", {"query": "یزد"})).structured_content
    assert r["cities"][0]["code"] == "AZD"


async def test_live_buses(client):
    r = (
        await client.call_tool("al_buses", {"origin": "تهران", "destination": "اصفهان", "date": DAY, "limit": 5})
    ).structured_content
    assert r["found"] > 0 and r["buses"][0]["price_toman"] > 100_000, r


async def test_live_flights(client):
    r = (
        await client.call_tool("al_flights", {"origin": "THR", "destination": "SYZ", "date": DAY, "limit": 5})
    ).structured_content
    assert r["found"] > 0 and r["flights"][0]["price_toman"] > 1_000_000, r


async def test_live_flights_cheapest(client):
    r = (
        await client.call_tool("al_flights_cheapest", {"origin": "THR", "destination": "MHD", "date": DAY, "days": 5})
    ).structured_content
    assert r["days"] and r["cheapest"]["price_toman"] > 1_000_000, r


async def test_live_trains_or_site_maintenance(client):
    r = await client.call_tool("al_trains", {"origin": "THR", "destination": "MHD", "date": DAY, "limit": 5})
    if r.is_error:  # rail suppliers go offline for maintenance for a while, usually after midnight
        assert "ریلی" in r.content[0].text, r.content[0].text
    else:
        assert r.structured_content["found"] > 0 and r.structured_content["trains"][0]["price_toman"] > 100_000


async def test_live_trains_cheapest(client):
    r = await client.call_tool("al_trains_cheapest", {"origin": "THR", "destination": "MHD", "date": DAY})
    assert r.is_error or r.structured_content["days"]
