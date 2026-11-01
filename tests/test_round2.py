import json

import httpx
import pytest
from conftest import fixture

pytestmark = pytest.mark.anyio

P = "/api/"


async def _noop(*_):
    return None


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    from alibaba_ir_mcp import intl, lodging, tours, travel

    for m in (intl, lodging, tours, travel):
        monkeypatch.setattr(m.asyncio, "sleep", _noop)


async def test_cities_international_lists_airports(client, api):
    api[P + "v1/basic-info/airports/international"] = fixture("intl_airports.json")
    r = (await client.call_tool("al_cities", {"query": "Dubai", "international": True})).structured_content
    assert api.calls[0].url.params["filter"] == "q={ct:'Dubai'}"
    assert r["places"][0]["code"] == "DXBALL" and r["places"][0]["whole_city"] is True
    assert r["places"][0]["country"] == "امارات متحده عربی"
    r = await client.call_tool("al_cities", {"international": True})
    assert r.is_error and "name" in r.content[0].text


async def test_trains_round_trip_and_options(client, api):
    api[P + "v2/train/available"] = {"result": {"requestId": "R"}, "success": True}
    api[P + "v2/train/available/R"] = fixture("train_available_rt.json")
    r = (
        await client.call_tool(
            "al_trains",
            {
                "origin": "THR",
                "destination": "MHD",
                "date": "2026-11-12",
                "return_date": "1405-08-24",
                "passengers": 3,
                "ticket_type": "female",
                "only_available": False,
                "wagon_class": "ec",
            },
        )
    ).structured_content
    body = json.loads(api.calls[0].content)
    assert body["returnDate"] == "2026-11-15" and body["passengerCount"] == 3 and body["ticketType"] == "Female"
    assert r["trains"] and all(t["class_code"] == "EC" for t in r["trains"]) and r["returning"]
    assert "max_passengers" in r["trains"][0] and r["return_date"] == "2026-11-15"
    r = await client.call_tool(
        "al_trains", {"origin": "THR", "destination": "MHD", "date": "2026-11-12", "return_date": "2026-11-01"}
    )
    assert r.is_error and "before" in r.content[0].text


async def test_flights_round_trip_group_and_refund_rules(client, api):
    api[P + "v1/flights/domestic/available"] = {"result": {"requestId": "F"}, "success": True}
    api[P + "v1/flights/domestic/available/F"] = fixture("flights_available_rt.json")
    r = (
        await client.call_tool(
            "al_flights",
            {
                "origin": "THR",
                "destination": "SYZ",
                "date": "2026-11-12",
                "return_date": "2026-11-15",
                "adults": 2,
                "children": 1,
                "refund_rules": True,
            },
        )
    ).structured_content
    body = json.loads(api.calls[0].content)
    assert body["returnDate"] == "2026-11-15" and (body["adult"], body["child"], body["infant"]) == (2, 1, 0)
    f = r["flights"][0]
    assert f["child_price_toman"] and f["infant_price_toman"] and f["refund_penalties"]
    assert any("%" in v for v in f["refund_penalties"].values())
    assert r["returning"] and r["returning"][0]["refund_penalties"]
    r = (
        await client.call_tool("al_flights", {"origin": "THR", "destination": "SYZ", "date": "2026-11-12"})
    ).structured_content
    assert "refund_penalties" not in r["flights"][0] and "returning" not in r
    r = await client.call_tool(
        "al_flights", {"origin": "THR", "destination": "SYZ", "date": "2026-11-12", "adults": 1, "infants": 2}
    )
    assert r.is_error and "infant" in r.content[0].text


async def test_buses_with_no_result_say_why(client, api):
    api[P + "v1/bus/stations"] = fixture("bus_stations.json")
    api[P + "v2/bus/available"] = {
        "result": {
            "firstNextAvailableDate": "2026-11-14T00:00:00",
            "firstNextAvailablePrice": 7000000.0,
            "routeAvailability": "TemporarilyUnavailable",
            "availableList": [],
        },
        "success": True,
    }
    r = (
        await client.call_tool("al_buses", {"origin": "THR", "destination": "MHD", "date": "2026-11-11"})
    ).structured_content
    assert r["found"] == 0 and r["route_status"] == "TemporarilyUnavailable"
    assert r["next_available_date"] == "2026-11-14" and r["next_available_price_toman"] == 700000


async def test_buses_cheapest_one_search_per_day(client, api):
    api[P + "v1/bus/stations"] = fixture("bus_stations.json")
    api[P + "v2/bus/available"] = fixture("bus_available.json")
    r = (
        await client.call_tool(
            "al_buses_cheapest", {"origin": "THR", "destination": "MHD", "date": "2026-11-11", "days": 3}
        )
    ).structured_content
    days = [c.url.params["requestDate"] for c in api.calls if c.url.path.endswith("v2/bus/available")]
    assert days == ["2026-11-11", "2026-11-12", "2026-11-13"]
    assert len(r["days"]) == 3 and r["cheapest"]["price_toman"] == min(d["price_toman"] for d in r["days"])
    assert r["days"][0]["buses"] > 0


async def test_bus_seats_picks_bus_by_time(client, api):
    api[P + "v1/bus/stations"] = fixture("bus_stations.json")
    api[P + "v2/bus/available"] = fixture("bus_available.json")
    api[P + "v1/bus/available/seats"] = fixture("bus_seats.json")
    r = (
        await client.call_tool(
            "al_bus_seats",
            {"origin": "THR", "destination": "MHD", "date": "2026-11-11", "departure_time": "10:00"},
        )
    ).structured_content
    body = json.loads(api.calls[-1].content)
    assert body["proposalId"] and body["uniqueServiceToken"]
    assert r["status_counts"] == {"Available": 13, "BookedForMale": 12} and len(r["free_seats"]) == 13
    assert r["layout"][str(r["free_seats"][0])].startswith("r")
    assert "proposalId" not in r
    r = await client.call_tool(
        "al_bus_seats", {"origin": "THR", "destination": "MHD", "date": "2026-11-11", "departure_time": "03:15"}
    )
    assert r.is_error and "al_buses" in r.content[0].text


async def test_international_flights_collect_batches_and_filter(client, api):
    api[P + "v1/basic-info/airports/international"] = fixture("intl_airports.json")
    api[P + "v1/flights/international/proposal-requests"] = {"result": {"requestId": "I", "regionType": "ShortHaul"}}
    full = fixture("intl_proposals.json")
    first = json.loads(json.dumps(full))
    first["result"]["isCompleted"], first["result"]["proposals"] = False, full["result"]["proposals"][:2]
    last = json.loads(json.dumps(full))
    last["result"]["proposals"] = full["result"]["proposals"][1:]  # overlap: duplicates must not repeat
    batches = iter([first, last])
    api[P + "v1/flights/international/proposal-requests/I"] = lambda r: httpx.Response(200, json=next(batches))
    r = (
        await client.call_tool(
            "al_flights_international",
            {"origin": "dubai", "destination": "DXB", "date": "1405-08-25", "adults": 2, "max_stops": 0},
        )
    ).structured_content
    start = json.loads(
        next(c for c in api.calls if c.method == "POST" and c.url.path.endswith("proposal-requests")).content
    )
    assert start["origin"] == "DXBALL" and start["destination"] == "DXB" and start["adult"] == 2
    assert start["departureDate"] == "2026-11-16" and start["flightClass"] == "Economy" and "returnDate" not in start
    assert r["found"] == 3 and [f["price_toman"] for f in r["flights"]] == [17150000, 17315100, 17540600]
    f = r["flights"][0]
    assert f["segments"] and f["baggage"] and f["stops"] == 0 and f["duration_min"] > 0
    assert "proposalId" not in f and "uniqueId" not in f
    api[P + "v1/flights/international/proposal-requests/I"] = full
    r = (
        await client.call_tool(
            "al_flights_international",
            {"origin": "dubai", "destination": "DXB", "date": "2026-11-16", "airline": "ata", "sort": "departure"},
        )
    ).structured_content
    assert [f["airline"] for f in r["flights"]] == ["Ata Airlines"]


async def test_international_round_trip_has_return_leg(client, api):
    api[P + "v1/basic-info/airports/international"] = fixture("intl_airports.json")
    api[P + "v1/flights/international/proposal-requests"] = {"result": {"requestId": "J"}}
    api[P + "v1/flights/international/proposal-requests/J"] = fixture("intl_proposals_rt.json")
    r = (
        await client.call_tool(
            "al_flights_international",
            {"origin": "dubai", "destination": "DXB", "date": "2026-11-16", "return_date": "2026-11-20"},
        )
    ).structured_content
    start = json.loads(next(c for c in api.calls if c.url.path.endswith("proposal-requests")).content)
    assert start["returnDate"] == "2026-11-20"
    assert r["flights"][0]["return"]["departure"] and r["flights"][0]["total_toman"] > 30_000_000


async def test_stays_resolve_place_and_send_filters(client, api):
    api[P + "v2/accommodation/Available/Suggestions"] = fixture("stay_suggest.json")
    api[P + "v2/accommodation/Available/Search"] = fixture("stay_search.json")
    r = (
        await client.call_tool(
            "al_stays",
            {
                "destination": "ماسوله",
                "checkin": "1405-08-21",
                "nights": 2,
                "guests": 4,
                "type": "villa",
                "min_price": 1_000_000,
                "max_price": 5_000_000,
                "min_rating": 4,
                "instant_only": True,
                "sort": "price",
            },
        )
    ).structured_content
    assert api.calls[0].url.params["Keyword"] == "ماسوله"
    body = json.loads(api.calls[1].content)
    assert body["location"] == "city-masuleh" and body["pageSize"] == 100
    assert body["date"]["endTime"]["seconds"] - body["date"]["startTime"]["seconds"] == 2 * 86400
    f = body["filters"]
    assert f["capacity"] == 4 and f["accommodationTypes"] == ["villa"] and f["isInstant"] is True
    assert f["price"] == {"start": 10_000_000, "end": 50_000_000} and f["scores"] == ["4.0-5.0"]
    assert r["place"].startswith("ماسوله") and r["found"] == 165 and r["nights"] == 2
    prices = [s["price_per_night_toman"] for s in r["stays"]]
    assert prices == sorted(prices) and r["stays"][0]["name"]
    s = next(s for s in r["stays"] if s["id"] == "665b036b494125001b52d81a")
    assert (
        s["price_total_toman"] == 3_920_000 and s["price_per_night_toman"] == 1_960_000 and s["url"].endswith("-606121")
    )
    assert "images" not in s and "amenities" not in s


async def test_stays_slug_skips_suggestions_and_unknown_place_fails(client, api):
    api[P + "v2/accommodation/Available/Search"] = fixture("stay_search.json")
    await client.call_tool("al_stays", {"destination": "city-masuleh", "checkin": "2026-11-12"})
    assert [c.url.path for c in api.calls] == [P + "v2/accommodation/Available/Search"]
    api[P + "v2/accommodation/Available/Suggestions"] = {"result": {"suggestions": []}}
    r = await client.call_tool("al_stays", {"destination": "زززز", "checkin": "2026-11-12"})
    assert r.is_error and "No place found" in r.content[0].text


async def test_stay_detail_trims_and_hides_people(client, api):
    pid = "665b036b494125001b52d81a"
    api[P + f"v2/accommodation/Available/GetDetails/{pid}"] = fixture("stay_detail.json")
    api[P + f"v2/accommodation/Comment/Reviews/{pid}"] = fixture("stay_reviews.json")
    r = (await client.call_tool("al_stay_detail", {"id": pid, "calendar_days": 12, "reviews": 2})).structured_content
    assert r["name"] == "ویلا یک خوابه ادریس" and r["guests_base"] == 4 and r["guests_max"] == 8
    assert r["price_base"] == 1_500_000 and r["price_weekend"] == 2_000_000
    assert len(r["calendar"]) == 12 and r["calendar"][0]["available"] is False
    assert any(c["available"] and c["price_toman"] for c in r["calendar"])
    assert r["rules_allowed"] and r["cancellation"] and r["amenities"]
    assert r["url"] == "https://alibaba.ir/accommodation/pdp/villa-606121"
    assert len(r["reviews"]) == 2 and r["rating_breakdown"]
    text = json.dumps(r, ensure_ascii=False)
    for secret in ("ownerName", "hostInfo", "phone", "avatar", "userId"):
        assert secret not in text
    r = await client.call_tool("al_stay_detail", {"id": "zz"})
    assert r.is_error


async def test_hotels_search_then_result(client, api):
    api[P + "v3/hotel/suggest"] = fixture("hotel_suggest.json")
    api[P + "v1/hotel/search"] = fixture("hotel_search.json")
    api[P + "v1/hotel/result"] = fixture("hotel_result.json")
    r = (
        await client.call_tool(
            "al_hotels",
            {"city": "مشهد", "checkin": "1405-08-21", "nights": 2, "adults": 1, "min_stars": 4, "sort": "price"},
        )
    ).structured_content
    search = next(c for c in api.calls if c.url.path.endswith("hotel/search"))
    assert search.url.params["cityId"] == "7101575872318013473" and search.url.params["countryCode"] == "IR"
    sb = json.loads(search.content)
    assert (sb["checkIn"], sb["checkOut"]) == ("2026-11-12", "2026-11-14") and sb["rooms"][0]["adults"] == [30]
    rb = json.loads(api.calls[-1].content)
    assert rb["sessionId"] == "6ae67871a6ae642d149219c6" and rb["sort"] == {"order": 1, "field": "minPrice"}
    assert {"field": "star", "value": [4, 5]} in rb["filter"]
    assert r["found"] == 186 and r["hotels"][0]["name"] == "بین المللی قصر"
    h = r["hotels"][0]
    assert h["price_total_toman"] == 17_946_000 and h["price_per_night_toman"] == 8_973_000 and h["stars"] == 5
    assert "allFacilities" not in h


async def test_hotels_hotel_name_hint(client, api):
    api[P + "v3/hotel/suggest"] = {"results": [{"type": "hotel", "displayName": "هتل الماس", "cityName": "مشهد"}]}
    r = await client.call_tool("al_hotels", {"city": "الماس", "checkin": "2026-11-12"})
    assert r.is_error and "search that city" in r.content[0].text


async def test_tours_resolve_places_search_and_poll(client, api):
    api[P + "v1/tour/available-api/available/all-destinations"] = fixture("tour_destinations.json")
    api[P + "v1/tour/available-api/available/sources"] = fixture("tour_sources.json")
    api[P + "v1/tour/available-api/available/plp-chunksearch"] = fixture("tour_chunksearch.json")
    done = fixture("tour_result.json")
    wait = json.loads(json.dumps(done))
    wait["result"]["isFinished"], wait["result"]["plpItems"] = False, []
    answers = iter([wait, done])
    api[P + "v3/tour/available-api/available/plp-result"] = lambda r: httpx.Response(200, json=next(answers))
    r = (
        await client.call_tool(
            "al_tours", {"destination": "kish", "checkin": "1405-08-12", "nights": 3, "adults": 2, "sort": "price"}
        )
    ).structured_content
    q = next(c for c in api.calls if c.url.path.endswith("plp-chunksearch")).url.params
    assert q["origin"] == "iran-tehran" and q["destination"] == "iran-kish_island" and q["rooms"] == "2"
    assert q["from"] == "2026-11-03" and q["to"] == "2026-11-06"
    assert api.calls[-1].url.params["searchKey"] == "KEY1"
    assert r["found"] == 67 and r["to"] == "کیش" and len(r["tours"]) == 3
    t = r["tours"][0]
    assert t["price_per_person_toman"] == 18_695_000 and t["price_total_toman"] == 37_390_000
    assert t["transport"] == ["پرواز"] and t["stars"] and t["hotel"]
    prices = [t["price_per_person_toman"] for t in r["tours"]]
    assert prices == sorted(prices)
    r = await client.call_tool("al_tours", {"destination": "xyzxyz", "checkin": "2026-11-03"})
    assert r.is_error and "Popular ones" in r.content[0].text


async def test_tours_cheapest_calendar(client, api):
    api[P + "v1/tour/available-api/available/all-destinations"] = fixture("tour_destinations.json")
    api[P + "v1/tour/available-api/available/sources"] = fixture("tour_sources.json")
    api[P + "v1/tour/available-api/available/timetable/iran-tehran/iran-kish_island/2026-11-14/2026-11-17"] = fixture(
        "tour_timetable.json"
    )
    r = (
        await client.call_tool("al_tours_cheapest", {"destination": "کیش", "checkin": "1405-08-23", "nights": 3})
    ).structured_content
    assert len(r["days"]) == 11 and r["days"][0]["checkin"] == "2026-11-09"
    assert r["cheapest"] == {"checkin": "2026-11-11", "checkout": "2026-11-14", "price_per_person_toman": 19_750_300}
