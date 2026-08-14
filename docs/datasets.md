# Open dataset shortlist - REIT7820

Starting points for your Week 3 scoping. Covers the three domains the starter kit
supports: **EV Charging**, **Public Transport**, and **Policy & Fares**.

You are not limited to these, but whatever you choose **must be openly licensed**
(spec §8) and you must cite it in your `sources` array (D4) and your `health`
payload (§4.1).

Every endpoint below was checked on **8 August 2026**. Where something is fiddly,
the gotcha is written down - those are the hours you don't have to lose.

---

## How to pull anything from data.qld.gov.au

Most Queensland datasets are in a CKAN **datastore**, which means you can query
them as JSON instead of downloading and parsing a CSV:

```
https://www.data.qld.gov.au/api/3/action/datastore_search?resource_id=<ID>&limit=1000
```

Filtered, and via SQL:

```
.../datastore_search?resource_id=<ID>&q=brisbane
.../datastore_search_sql?sql=SELECT * FROM "<ID>" WHERE "Status" = 'Active'
```

Find the `resource_id` and whether the datastore is available:

```
https://www.data.qld.gov.au/api/3/action/package_show?id=<dataset-slug>
```

Look for `"datastore_active": true`. If it's `false`, you must download the file.

> **Prefer the API to the CSV.** The EV charging CSV, for example, contains
> embedded newlines inside quoted fields - the datastore returns the same rows as
> clean JSON. `data.py` in the starter kit uses this endpoint.

---

## EV Charging Infrastructure

**Queensland Electric Super Highway - charging stations** *(used by the starter kit)*
- Dataset: [find-a-charging-station-electric-vehicle](https://www.data.qld.gov.au/dataset/find-a-charging-station-electric-vehicle)
- `resource_id`: `a34d4b5f-8e3c-4995-8950-2e84fd7bb4d5` | datastore available | **CC BY 4.0** | no key
- 17 stations statewide, 6 in SEQ.
- **Gotchas:** it's the *highway backbone*, not a dense urban charger map - scope your tool accordingly. The `Charging plugs available` column is published but **empty for every row**; don't invent connector types. `Nearest QESH charging station` is useful free text ("Gatton: 92km West, Brisbane: 92km East").

**OpenChargeMap** - global registry, much denser coverage
- `https://api.openchargemap.io/v3/poi?output=json&countrycode=AU&latitude=...&longitude=...`
- **Free key required** (returns `403` without one) - register at openchargemap.org, then read it from `OPENCHARGEMAP_KEY` in `.env`, never in code (§8).
- Licence: ODbL. Community-maintained, so quality varies by area - sanity-check before trusting.

---

## Public Transport Journey Planning

**Translink SEQ GTFS (static)**
- Dataset: [general-transit-feed-specification-gtfs-translink](https://www.data.qld.gov.au/dataset/general-transit-feed-specification-gtfs-translink)
- ZIP download, not datastore | **CC BY 4.0** | no key
- Live URL: `https://gtfsrt.api.translink.com.au/GTFS/SEQ_GTFS.zip` - 28 MB compressed.
- Verified contents (8 Aug 2026): `stop_times.txt` **164 MB**, `shapes.txt` 36 MB, `trips.txt` 8.9 MB, `stops.txt` 1.6 MB, `routes.txt` 0.13 MB, plus `calendar`, `calendar_dates`, `feed_info`, `agency`.
- **Gotchas:** `stop_times.txt` is 164 MB uncompressed - **load and index once at startup; never parse it inside a tool call** (45 s budget, D5). Most questions only need `stops.txt` and `routes.txt`, which are small. Use `stop_id` / `route_id` verbatim - §5 requires Translink GTFS IDs.
- **No fare files** are in this archive - see Transport Policy & Fares below.

**Translink GTFS-Realtime**
- Dataset: [translink-real-time-data](https://www.data.qld.gov.au/dataset/translink-real-time-data) - Trip Updates, Vehicle Positions, Service Alerts
- **CC BY 4.0** | no key
- **Gotchas:** Protocol Buffers, not JSON - you need `gtfs-realtime-bindings`. Feeds refresh every ~15-30 s; cache and state your freshness in the tool description.

---

## Transport Policy & Fares

> **Correction to the theme document.** It lists *"Translink GTFS fare data"*.
> That data does not exist. `SEQ_GTFS.zip` was downloaded and its contents listed
> on 8 August 2026: it contains `stop_times`, `shapes`, `trips`, `stops`,
> `routes`, `calendar`, `calendar_dates`, `feed_info` and `agency`.
> **`fare_attributes.txt` and `fare_rules.txt` are absent.** There is also no
> machine-readable fare table anywhere on data.qld.gov.au.
>
> More importantly, **there is no fare structure left to model.** Translink's own
> site states: *"50 cent fares are here - Public transport fares are a 50 cent
> flat rate across all Translink services."* A fare calculator would return
> `"0.50"` every time.
>
> Build this domain on **patronage and policy impact** instead. The data is
> genuinely good, and the fare change itself is the research question.

**The 50c fare change is a natural experiment.** Fares dropped to a flat 50 cents
in **August 2024**, and the monthly series spans that date. SEQ bus trips:

| Month | Bus trips |
|---|---|
| Jul-2024 | 9,640,655 |
| **Aug-2024** | **10,804,273** ← 50c fares begin |
| Oct-2024 | 11,101,075 |

A before/after comparison across modes is a defensible thesis question with real
public data - far stronger than a calculator over a constant.

**Patronage - South East Queensland**
- Dataset: [translink-monthly-performance-data](https://www.data.qld.gov.au/dataset/translink-monthly-performance-data)
- `resource_id`: `c49df919-5c0d-4bd2-9e43-776509b95ef6` | datastore available | **CC BY 3.0** | no key
- 116 rows, **Dec-2023 to Apr-2026**, modes: Bus, Citytrain, Ferry, Tram
- Fields: `Month-Year`, `Mode`, `Passenger trips`

**Patronage and complaints (weekly)**
- `resource_id`: `c4a1cf64-aca9-4447-96eb-55baf5bee31e` | datastore available | **CC BY 3.0**
- **712 rows back to 2012** - weekly resolution, plus complaints per 10,000 trips
- The strongest series here: long enough for a trend, fine enough to see a policy
  change, and it pairs volume with a service-quality measure.
- **Gotcha:** several field names contain embedded newlines
  (`"Customer complaints on \ngo card"`). Read them from the API's `fields` list
  rather than typing them.

**Patronage - Rest of Queensland**
- `resource_id`: `ab30c308-7bea-4f47-8813-d6536532db93` | datastore available | 145 rows
- Regional modes including Regional Air. **Not SEQ** - check your stated coverage.

**Translink Origin-Destination Trips, 2022 onwards**
- Dataset: [translink-origin-destination-trips-2022-onwards](https://www.data.qld.gov.au/dataset/translink-origin-destination-trips-2022-onwards) | **CC BY 4.0**
- Where people travel from and to, not just how many. Good for demand questions.

**Gotchas across all of these**
- `Passenger trips` arrives as a **string** in the monthly series and a **float**
  in the weekly one. Cast explicitly.
- `Month-Year` is `"Dec-2023"` - parse with `%b-%Y`, and remember §5 wants ISO 8601
  with a timezone in anything you return.
- Money, if you report any, is a decimal string: `"0.50"` (§5, `smac.money()`).

---

## Also used by the starter kit

**Nominatim (OpenStreetMap)** - place name to coordinates
- `https://nominatim.openstreetmap.org/search?q=...&format=json` | **ODbL** | no key
- The kit's `geocode_place` tool uses this so a model never has to guess a
  coordinate. Asked for "University of Queensland, St Lucia", a model returned a
  point **261 m** from OpenStreetMap's - a recalled coordinate has no source and
  cannot be cited (D4).
- **Gotchas:** **max 1 request/second** and a descriptive `User-Agent` is
  mandatory - 55 agents calling it live would get the cohort blocked. Cache hard
  (`data.py` caches a month). Check the returned `class`/`type`: "Chermside
  Shopping Centre" resolves to a *bus stop* unless you query "Westfield Chermside".

> **Google Maps is not permitted** - proprietary licence, its Terms of Service
> restrict storing results, and it requires a billed key. That fails §8.

---

## Choosing well - what actually matters at Week 3

1. **Can you fetch it without a key, or with a free one?** Paid or approval-gated sources will stall you.
2. **Is it small enough to load at startup?** Anything needing a big parse inside a tool call will breach the 45 s budget (D5).
3. **Can you build ground truth from it?** Your evaluation needs verifiable right answers. Record where each answer came from as you build it.
4. **Does it have holes?** Real datasets do. Reporting a gap honestly beats inventing a field - and it's part of the Showcase rubric (§6).
