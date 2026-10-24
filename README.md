# European hotel room database

An accumulating list of hotels across Europe, including independent and branded properties. Collects hotel names, **total guest-room counts**, addresses, coordinates, brands, source URLs and observation dates. It does not collect individual room identifiers or room categories.

## Download the list

- [All discovered hotels, Excel-compatible CSV](exports/hotels.csv)
- [Hotels with a sourced room total, Excel-compatible CSV](exports/hotels-with-rooms.csv)
- [Country coverage and room-count coverage](exports/coverage.json)
- [Country snapshots for database imports](data/countries)
- [Run history and next country](data/state.json)

CSV files are UTF-8 with a BOM for Excel. If Excel puts everything in one column, use Data → From Text/CSV and select comma. Formula-like text is prefixed with an apostrophe in CSV; original values remain in JSON. Room totals are integers; missing totals are blank, never zero. IDs and postcode text should be imported as text.

## Weekly collection

GitHub Actions runs Sundays at **02:23 UTC** (03:23 Zurich winter time; 04:23 summer time). One country is discovered per run, starting with Germany, then Austria, Switzerland and the remaining entries in [scope.json](scope.json). The queue loops after its last entry. With 57 countries and territories, a full pass takes 57 weekly runs; countries are not all refreshed every week. Failed imports retain the cursor and prior snapshot for the next attempt.

Each run also checks up to 200 hotel websites from a fair queue across all collected countries. A 35-minute soft budget and a 55-minute workflow limit bound the work. Checks are serial, at least five seconds apart, and follow robots.txt. A website is eligible again after 90 days. Public sites may refuse requests or omit totals; these outcomes are recorded.

Use the Actions tab → Weekly European hotel collection → Run workflow to run it immediately. No paid APIs, API keys, accounts or external database hosting are required. Standard GitHub-hosted runners are [free for public repositories](https://docs.github.com/en/billing/concepts/product-billing/github-actions). The workflow uses no billed artifact storage or paid services. GitHub may delay scheduled jobs or [disable schedules after 60 days without repository activity](https://docs.github.com/en/actions/managing-workflow-runs-and-deployments/managing-workflows/disabling-and-enabling-a-workflow); normal data/checkpoint commits keep this repository active.

## What the data means

Discovery uses OpenStreetMap's `tourism=hotel`, without filtering by brand, room count, name or address completeness. This includes independent hotels. Hostels, holiday apartments, guest houses and objects tagged only `building=hotel` are excluded. A hotel absent from OSM will be absent from this initial discovery source. A missing brand means **unknown affiliation**, not proof of independence.

The `rooms` column comes from either OSM's explicit [`rooms` tag](https://wiki.openstreetmap.org/wiki/Key:rooms) (`community_reported`) or an identity-matched hotel website's [`Hotel.numberOfRooms`](https://schema.org/Hotel) structured data (`website_structured_reported`). HotelRoom objects, bed counts, capacity, category counts, ranges and conflicting totals are rejected. A total is a sourced assertion, not an audited figure. Name matching is conservative, but hotel websites and community data can contain errors. Source URLs, evidence and observation dates are included for review. Free text and PDFs require future source-specific adapters; the collector leaves those totals unknown.

This is **not a complete census of every European hotel**. Coverage reports show discovered rows and known room counts, not a percentage of all real hotels. Some addresses and brands are missing. Coordinates are OSM points or geometry centres, suitable as map candidates rather than surveyed entrances. Exact normalized names within a small coordinate tolerance are flagged as possible duplicates and retained for review; do not sum flagged rows without resolving them. Source disappearance is not treated as hotel closure; previously seen rows are retained with their last-seen date.

Transcontinental and boundary countries are collected in full and flagged `full_transcontinental_country`, including their non-European parts. This prevents silently excluding hotels in contested definitions of Europe and allows a later geographic filter. Overseas areas separately coded in OSM are outside the listed scope. Administrative boundary membership follows OSM.

## Run locally and import into a database

Python 3.11 or later; standard library only:

```sh
python -m unittest discover -s tests -v
python collector.py
python collector.py --country DE --enrich-limit 20
python collector.py --export-only --database
```

An explicit `--country` refresh does not move the scheduled cursor. `--export-only --database` creates `exports/hotels.sqlite` and `exports/hotels.geojson` locally for SQL and mapping platforms. CSV and country JSON files are committed; large binary databases and redundant GeoJSON snapshots are not maintained in Git history. `hotel_id` is the stable source key. Node/way duplicates and reflagged hotels still need identity reconciliation.

Country snapshots are saved after discovery and each website check. Exports are replaced atomically. Run errors remain visible in `data/state.json` and fail the GitHub job after checkpoint data is committed. There are no requests for availability or room rates.

## Sources and reuse

© [OpenStreetMap contributors](https://www.openstreetmap.org/copyright). The OSM-derived database is subject to [ODbL 1.0](https://opendatacommons.org/licenses/odbl/1-0/). Preserve attribution and comply with share-alike requirements when distributing adapted databases. Hotel website assertions retain their source rights; public access does not establish a separate reuse licence. Only short structured evidence is retained.

The public [Overpass service](https://dev.overpass-api.de/overpass-doc/en/preface/commons.html) is shared infrastructure: one country query per weekly run, no parallel crawling, no attempts to bypass rate limits or access restrictions. Availability is not guaranteed. For a substantially larger workload, use country extracts or your own infrastructure. Collection code is MIT licensed; source data has the separate terms above.
