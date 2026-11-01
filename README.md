<!-- mcp-name: io.github.sepehr071/alibaba-ir-mcp -->

<div align="center">

# alibaba-ir-mcp: Alibaba (علی‌بابا) Iran train, bus, flight, hotel, villa and tour search MCP server for AI agents

**alibaba-ir-mcp is an unofficial, read-only MCP server that gives AI agents the train, bus, flight, hotel, villa and tour listings of Alibaba (alibaba.ir), Iran's largest travel site.**<br>
Its 14 tools look up city codes, search trains, buses, domestic and international flights, hotels, holiday homes and tour packages with prices and availability,<br>
show bus seat maps and find the cheapest day to travel. No API key or Alibaba account is needed. It works in Claude, Cursor, Copilot and any other MCP client.

[![PyPI](https://img.shields.io/pypi/v/alibaba-ir-mcp?color=2563eb)](https://pypi.org/project/alibaba-ir-mcp/)
[![Python](https://img.shields.io/pypi/pyversions/alibaba-ir-mcp)](https://pypi.org/project/alibaba-ir-mcp/)
[![CI](https://github.com/sepehr071/alibaba-ir-mcp/actions/workflows/ci.yml/badge.svg)](https://github.com/sepehr071/alibaba-ir-mcp/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-16a34a)](https://github.com/sepehr071/alibaba-ir-mcp/blob/main/LICENSE)

[For AI agents](#for-ai-agents) · [Quick start](#quick-start) · [Tools](#tools) · [FAQ](#faq) · [فارسی](#فارسی)

</div>

---

## For AI agents

- **What:** unofficial MCP server (model context protocol) for alibaba.ir: train tickets (company, class, compartments, price, seats left, round trips), intercity buses (company, bus type, terminals, price, free seats), domestic and international flights (airline, times, fare classes, baggage, refund fees, round trips), hotels, villa and holiday-home rentals, tour packages and the cheapest day per route.
- **Install:** `uvx alibaba-ir-mcp` or `claude mcp add alibaba -- uvx alibaba-ir-mcp`. Transport: stdio. Needs [uv](https://docs.astral.sh/uv/getting-started/installation/) (Python 3.10+).
- **Auth:** none, no API key or account. Optional `ALIBABA_IR_MCP_PROXY` (HTTP proxy URL, or a comma-separated list); system proxy settings are ignored.
- **Access:** read-only. It cannot log in, book, hold seats or pay, so no confirmation is needed before calling any tool.
- **Tools:** 14, all prefixed `al_`. Typical sequences: `al_trains` / `al_buses` / `al_flights` / `al_flights_international` for one day; `al_*_cheapest` then the search for the chosen day; `al_stays` then `al_stay_detail`; `al_cities` when unsure of a city code.
- **Use when:** the user asks for train, bus or flight options, prices or seats, a hotel, a villa to rent or a tour package, or the cheapest day to travel.
- **Do not use when:** the user wants to buy or book (send them to alibaba.ir), or asks about visas and insurance (not covered).
- **Output:** compact JSON. Prices are Toman (Alibaba's API uses Rial; the tools divide by 10 as the site does): per adult for transport, for the whole stay for hotels, villas and tours. Dates are accepted as Gregorian `2026-11-11` or Jalali `1405-08-20`; times are Iran local time.
- **Machine-readable:** [`server.json`](https://github.com/sepehr071/alibaba-ir-mcp/blob/main/server.json).

## Quick start

```bash
claude mcp add alibaba -- uvx alibaba-ir-mcp
```

Other clients: `{"command": "uvx", "args": ["alibaba-ir-mcp"]}`.

## Tools

| Tool | What it does |
|---|---|
| `al_cities` | City and airport names to the codes the other tools take (THR, MHD, SYZ...); `international=true` searches airports worldwide. |
| `al_trains` | Trains on one day (or a round trip): company, class and compartment, departure and arrival, price, seats left, discount; filter by class, passengers, women-only or men-only compartments. |
| `al_trains_cheapest` | Lowest train price for each of the next days. |
| `al_buses` | Intercity buses on one day: company, bus type, departure, price, seats, terminals, stops; says when a route has no buses and the next date that has. |
| `al_buses_cheapest` | Lowest bus price and bus count for each of the next days. |
| `al_bus_seats` | Free seats of one bus: counts per status, seat numbers and rows. |
| `al_flights` | Domestic flights on one day (or round trip): airline, flight number, times, aircraft, fare class, price per adult, child and infant, seats, baggage, cancellation fees. |
| `al_flights_cheapest` | Lowest domestic fare for each of the next days. |
| `al_flights_international` | International flights (any city Alibaba sells): airline, segments, stops, duration, baggage, price, round trip. |
| `al_stays` | Villas, suites, cottages and other holiday homes in a city: price, rating, capacity, filters for type, price, rating. |
| `al_stay_detail` | One holiday home: beds, amenities, house rules, cancellation terms, nightly price calendar, reviews. |
| `al_hotels` | Hotels in a city (Iran and abroad): stars, rating, price for the stay, meal plan, perks. |
| `al_tours` | Tour packages (travel plus hotel) to Kish, Mashhad, Istanbul, Dubai and more: hotel, room, price per person. |
| `al_tours_cheapest` | Lowest tour price per person for 11 days around a date. |

Example: "cheapest way from Tehran to Mashhad next Thursday" -> `al_trains_cheapest`, `al_flights_cheapest`, then
`al_trains` / `al_flights` / `al_buses` for that day.

## FAQ

**Is this official?** No. It reads the same public JSON the alibaba.ir web app loads for anyone without an account.

**Why does a train search sometimes fail?** The rail suppliers go offline for maintenance for a while, usually just
after midnight Tehran time. The site shows the same message; try again in a few minutes.

**Why are there several rows for one flight?** Each fare class is its own row; the site hides the repeats by default.

**Where do the villas come from?** Alibaba resells Jabama's listings; `al_stays` shows the same places and prices as alibaba.ir/accommodation.

**Does it work outside Iran?** Yes on most networks, directly or through `ALIBABA_IR_MCP_PROXY`.

## فارسی

سرور MCP غیررسمی و فقط‌خواندنی برای علی‌بابا (alibaba.ir): جستجوی قطار، اتوبوس، پرواز داخلی و خارجی، هتل، ویلا و تور با قیمت و ظرفیت، نقشه صندلی اتوبوس و ارزان‌ترین روز سفر.
نصب: `uvx alibaba-ir-mcp`. قیمت‌ها به تومان و تاریخ‌ها به شمسی (۱۴۰۵-۰۸-۲۰) یا میلادی پذیرفته می‌شود. خرید بلیت از طریق این ابزار ممکن نیست.

MIT License. Sepehr Radmard (سپهر رادمرد): github.com/sepehr071
