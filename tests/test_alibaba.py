import json
from datetime import date

import httpx
import pytest
from conftest import fixture

from alibaba_ir_mcp.travel import jalali_to_gregorian, parse_day

pytestmark = pytest.mark.anyio

TOOLS = {
    "al_cities",
    "al_trains",
    "al_trains_cheapest",
    "al_buses",
    "al_buses_cheapest",
    "al_bus_seats",
    "al_flights",
    "al_flights_cheapest",
    "al_flights_international",
    "al_stays",
    "al_stay_detail",
    "al_hotels",
    "al_tours",
    "al_tours_cheapest",
}
P = "/api/"


def test_jalali_dates():
    assert jalali_to_gregorian(1405, 8, 20) == date(2026, 11, 11)  # checked on alibaba.ir: 1405-08-20 -> 2026-11-11
    assert jalali_to_gregorian(1404, 12, 29) == date(2026, 3, 20)
    assert parse_day("1405/08/21") == date(2026, 11, 12)
    assert parse_day("2026-11-12") == date(2026, 11, 12)


async def test_all_tools_are_read_only_and_described(client):
    tools = (await client.list_tools()).tools
    assert {t.name for t in tools} == TOOLS
    for t in tools:
        assert t.annotations.read_only_hint is True, t.name
        assert t.title and t.description.splitlines()[0].endswith("."), t.name
        assert "title" not in str(t.input_schema.get("properties", {}).values()), t.name


async def test_cities_search_by_persian_and_english(client):
    r = (await client.call_tool("al_cities", {"query": "مشهد"})).structured_content
    assert r["cities"][0]["code"] == "MHD" and r["cities"][0]["flight"] is True
    r = (await client.call_tool("al_cities", {"query": "shiraz"})).structured_content
    assert [c["code"] for c in r["cities"]] == ["SYZ"]


async def test_trains_start_then_fetch_and_trim(client, api):
    api[P + "v2/train/available"] = {"result": {"requestId": "REQ1"}, "success": True}
    api[P + "v2/train/available/REQ1"] = fixture("train_available.json")
    r = (
        await client.call_tool("al_trains", {"origin": "تهران", "destination": "Mashhad", "date": "1405-08-20"})
    ).structured_content
    body = json.loads(api.calls[0].content)
    assert body["origin"] == "THR" and body["destination"] == "MHD" and body["departureDate"] == "2026-11-11"
    assert r["found"] == 4 and r["available"] == 2
    assert [t["train"] for t in r["trains"]] == [370, 318]  # sold out hidden, sorted by departure
    t = next(t for t in r["trains"] if t["train"] == 318)
    assert t["price_toman"] == 915050 and t["seats_left"] == 175 and t["duration_min"] > 0
    r = (
        await client.call_tool(
            "al_trains",
            {"origin": "THR", "destination": "MHD", "date": "2026-11-11", "only_available": False, "sort": "price"},
        )
    ).structured_content
    assert len(r["trains"]) == 4 and r["trains"][0]["price_toman"] == 915050


async def test_trains_report_the_sites_maintenance_message(client, api):
    msg = "<div><div class='x'>ارتباط با تامین کنندگان ریلی برقرار نیست.</div></div>"
    api[P + "v2/train/available"] = lambda r: httpx.Response(
        500, json={"result": None, "success": False, "error": {"errorCode": 1, "message": msg}}
    )
    r = await client.call_tool(
        "al_trains",
        {"origin": "THR", "destination": "MHD", "date": "2026-11-11"},
    )
    assert (
        r.is_error
        and "ارتباط با تامین کنندگان ریلی برقرار نیست." in r.content[0].text
        and "<div" not in r.content[0].text
    )
    assert len(api.calls) == 1  # no retries for a readable site error


async def test_trains_cheapest(client, api):
    api[P + "v2/train/available/cheapest"] = fixture("train_cheapest.json")
    r = (
        await client.call_tool(
            "al_trains_cheapest", {"origin": "THR", "destination": "MHD", "date": "2026-11-12", "days": 3}
        )
    ).structured_content
    assert len(r["days"]) == 3 and r["cheapest"]["price_toman"] == 915050
    assert json.loads(api.calls[0].content)["fromDate"] == "2026-11-12"


async def test_buses_resolve_city_codes_and_trim(client, api):
    api[P + "v1/bus/stations"] = fixture("bus_stations.json")
    api[P + "v2/bus/available"] = fixture("bus_available.json")
    r = (
        await client.call_tool(
            "al_buses", {"origin": "THR", "destination": "MHD", "date": "1405-08-20", "sort": "price"}
        )
    ).structured_content
    q = api.calls[-1].url.params
    assert q["orginCityCode"] == "11320000" and q["requestDate"] == "2026-11-11" and q["serviceType"] == "Bus"
    assert api.calls[0].url.params["filter"] == "q={ct:'THR'}"
    b = r["buses"][0]
    assert (
        b["price_toman"] == 1315000 and b["seats_left"] > 0 and "proposalId" not in b and "uniqueServiceToken" not in b
    )
    assert b["from_terminal"] and b["stops"]


async def test_flights_post_then_get_and_poll_until_complete(client, api, monkeypatch):
    from alibaba_ir_mcp import travel

    monkeypatch.setattr(travel.asyncio, "sleep", lambda s: _noop())
    api[P + "v1/flights/domestic/available"] = {"result": {"requestId": "FREQ"}, "success": True}
    full = fixture("flights_available.json")
    partial = json.loads(json.dumps(full))
    partial["result"]["isCompleted"], partial["result"]["departing"] = False, partial["result"]["departing"][:1]
    answers = iter([partial, full])
    api[P + "v1/flights/domestic/available/FREQ"] = lambda r: httpx.Response(200, json=next(answers))
    r = (
        await client.call_tool(
            "al_flights", {"origin": "THR", "destination": "MHD", "date": "2026-11-11", "sort": "price"}
        )
    ).structured_content
    assert json.loads(api.calls[0].content)["origin"] == "thr"
    assert r["found"] == 4  # the second poll returned the complete list
    f = r["flights"][0]
    assert f["flight"] == "ZV4040" and f["price_toman"] == 9921100 and f["airline"] == "زاگرس" and f["seats_left"] == 10
    assert "proposalId" not in f


async def _noop():
    return None


async def test_flights_cheapest(client, api):
    api[P + "v2/flights/domestic/available/cheapest"] = fixture("flights_cheapest.json")
    r = (
        await client.call_tool(
            "al_flights_cheapest", {"origin": "تهران", "destination": "شیراز", "date": "1405-08-21", "days": 3}
        )
    ).structured_content
    body = json.loads(api.calls[0].content)
    assert body["origin"] == "thr" and body["destination"] == "syz" and body["forwardDay"] == 2
    assert body["referenceDate"] == "2026-11-12"
    assert r["cheapest"]["price_toman"] == min(d["price_toman"] for d in r["days"])


async def test_unknown_or_ambiguous_city_lists_choices(client, api):
    r = await client.call_tool("al_trains", {"origin": "xyz", "destination": "MHD", "date": "2026-11-11"})
    assert r.is_error and "al_cities" in r.content[0].text
    r = await client.call_tool("al_trains", {"origin": "خرم", "destination": "MHD", "date": "2026-11-11"})
    assert r.is_error and "Did you mean" in r.content[0].text
    assert api.calls == []


async def test_blocked_request_message(client, api):
    api[P + "v1/bus/stations"] = lambda r: httpx.Response(403, text="denied")
    r = await client.call_tool("al_buses", {"origin": "THR", "destination": "MHD", "date": "2026-11-11"})
    assert r.is_error and "403" in r.content[0].text and "ALIBABA_IR_MCP_PROXY" in r.content[0].text


async def test_requests_look_like_the_web_app(api):
    from alibaba_ir_mcp import http

    ok = {"success": True, "result": {}}
    api["/api/v1/x"] = ok
    await http.fetch("v1/x")
    await http.fetch("v1/x", body={"a": 1})
    for r in api.calls:
        h = r.headers
        assert h["accept"] == "application/json, text/plain, */*" and h["origin"] == "https://www.alibaba.ir"
        assert h["referer"] == "https://www.alibaba.ir/" and h["sec-fetch-site"] == "same-site"
        assert len(h["ab-alohomora"]) == 22 and h["tracing-sessionid"].isdigit()
        assert h["ab-channel"].startswith("WEB-NEW,PRODUCTION,CSR,www.alibaba.ir,desktop,Chrome,")
        assert h["tracing-device"].startswith("N,Chrome,") and "Headless" not in h["ab-channel"]
    assert api.calls[1].headers["content-type"] == "application/json"
