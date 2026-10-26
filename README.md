# European hotel room database

An accumulating list of hotels across Europe, including independent and branded properties. Collects hotel names, **total guest-room counts**, addresses, coordinates, brands, source URLs and observation dates. It does not collect individual room identifiers or room categories.

## Download the list

- [All discovered hotels, Excel-compatible CSV](exports/hotels.csv)
- [Full compressed CSV download](exports/hotels.csv.gz)
- [Country CSV parts](exports/countries)
- [Hotels with a sourced room total, Excel-compatible CSV](exports/hotels-with-rooms.csv)
- [Country coverage and room-count coverage](exports/coverage.json)
- [Country snapshots for database imports](data/countries)
- [Run history and full Europe refresh status](data/state.json)

CSV files are UTF-8 with a BOM for Excel. If Excel puts everything in one column, use Data → From Text/CSV and select comma. Formula-like text is prefixed with an apostrophe in CSV; original values remain in JSON. Room totals are integers; missing totals are blank, never zero. IDs and postcode text should be imported as text.

## Brand discovery catalogue

Hotelier.de brand, group, operator and cooperation names are available in the [review CSV](exports/brand-discovery.csv) and [structured discovery catalogue](data/brand-discovery/hotelier.json). Entries retain source links, exact name comparison results and an explicit unverified status. Candidates do not automatically change hotel affiliations or parent mappings. The bounded index refresh runs monthly or manually; see [verification and hosting details](docs/brand-discovery.md).

## Weekly collection

GitHub Actions runs Sundays at **02:23 UTC** (03:23 Zurich winter time; 04:23 summer time). **Every weekly run attempts every one of the 57 countries and territories** in [scope.json](scope.json), serially, starting with Germany. There is a 15-second pause between countries. A failed request preserves that country's previous snapshot, records the failure and continues with the other countries. The job reports failure if any country could not be refreshed; it never labels that pass complete. Country source timestamps and the latest pass's successful, failed and pending countries are available in coverage and state files. A completed pass means the configured sources were refreshed, not that every real European hotel was discovered.

Each run also refreshes France's classified-hotel register, then checks up to 200 hotel websites from a fair queue across all collected sources. Room-count research has a separate 35-minute soft budget; the whole workflow allows up to five hours for the European OSM pass, register and research. Website checks are serial, at least five seconds apart, and follow robots.txt. A website is eligible again after seven days. Public sites may refuse requests or omit totals; these outcomes are recorded. Country records and registry room assertions are downloaded weekly when requests succeed. Individual website totals retain their evidence dates and are not all reverified weekly. An interrupted OSM pass restarted within 24 hours resumes its pending and failed countries, preserving successful country checkpoints.

## Free Google Maps discovery

A second [weekly workflow](.github/workflows/google.yml) starts Sundays at 09:17 UTC and attempts every European country. It runs the MIT-licensed [gosom Google Maps scraper](https://github.com/gosom/google-maps-scraper), pinned to v1.18.1 with a verified binary checksum, directly on standard GitHub runners. It uses no paid API, paid proxy or scraping-service credits. Two countries can run at a time, each using one scraper worker and up to 165 minutes of collection. Each country job allows three hours; the worst-case 57-country schedule fits within the week.

Localities are taken from the free [GeoNames cities500 dataset](https://download.geonames.org/export/dump/), not limited to capitals or places already in OSM. GeoNames is attributed under CC BY 4.0. This locality list itself is not every hamlet or hotel location. Google searches can truncate results, be blocked, or exceed the country time budget. Coverage files record actual observations, planned locality searches, process failures and time limits. All country jobs being attempted is not proof that every search or every Google hotel was collected. These remain partial observations, not a complete Google census.

Google contributes names, addresses, coordinates, source links and hotel websites. It does not reliably publish a room-total field. The collector finds totals separately in official registers and hotel website structured data or explicit total-room statements. Non-hotel results, review counts, ratings, bed counts and room-type capacities are excluded. No reviews, reviewer profiles, phone numbers or emails are retained in hotel exports. Cross-border search results are excluded when the listing country identifies another country; an unknown country is flagged for review.

The live validation search for Vaduz, Liechtenstein returned 22 Google listings, of which 15 were hotels. Hotel Vaduzerhof's official website explicitly supplied 35 rooms. This proves the free path works for that sample, not Europe-wide completeness or reliability. Source JSON snapshots and source-coverage files preserve the evidence.

Use the Actions tab → Weekly European hotel collection → Run workflow to run it immediately. No paid APIs, API keys, accounts or external database hosting are required. Standard GitHub-hosted runners are [free for public repositories](https://docs.github.com/en/billing/concepts/product-billing/github-actions). The workflow uses no billed artifact storage or paid services. GitHub may delay scheduled jobs or [disable schedules after 60 days without repository activity](https://docs.github.com/en/actions/managing-workflow-runs-and-deployments/managing-workflows/disabling-and-enabling-a-workflow); normal data/checkpoint commits keep this repository active.

## What the data means

Discovery uses OpenStreetMap's `tourism=hotel`, without filtering by brand, room count, name or address completeness. This includes independent hotels. Hostels, holiday apartments, guest houses and objects tagged only `building=hotel` are excluded. A hotel absent from OSM will be absent from this initial discovery source. A missing brand means **unknown affiliation**, not proof of independence.

Google discovery uses the free self-hosted scraper described above, rather than the billed Places API. France's [official classified accommodation register](https://www.data.gouv.fr/datasets/hebergements-touristiques-classes-en-france) adds named hotels, addresses and explicit room counts under Licence Ouverte. The import excludes non-hotels and overseas postcode areas; unclassified hotels are absent from that register. Its initial 13,116 hotel rows resolve to 13,113 distinct name/address identities, using the newest classification when the register repeats a property. A weekly download does not imply the authority inspected every room count that week.

The `rooms` column uses OSM's explicit [`rooms` tag](https://wiki.openstreetmap.org/wiki/Key:rooms) (`community_reported`), a register's room field (`registry_reported`), an identity-matched website's [`Hotel.numberOfRooms`](https://schema.org/Hotel) structured data (`website_structured_reported`), or an explicit total-room statement on an identity-matched property page (`website_text_reported`). HotelRoom objects, bed counts, capacity, category counts and ranges are rejected. Conflicting cross-source totals are flagged for review. A total is a sourced assertion, not an audited figure. Source URLs, evidence and observation dates are retained. PDFs and ambiguous prose need source-specific adapters; those totals remain unknown.

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

The default command refreshes the full country list. An explicit `--country DE` refreshes Germany only for troubleshooting. `--export-only --database` creates `exports/hotels.sqlite` and `exports/hotels.geojson` locally for SQL and mapping platforms. CSV and country JSON files are committed; large binary databases and redundant GeoJSON snapshots are not maintained in Git history. `hotel_id` is the stable source key. Node/way duplicates and reflagged hotels still need identity reconciliation.

Full compressed CSV downloads are always generated. Plain combined CSV files are retained while under 85 MiB; above that size, use the compressed download or country parts of at most 10,000 rows each. This avoids GitHub's 100 MiB file limit. Unzip the `.csv.gz` file before opening in Excel. The country JSON snapshots remain the database import source.

Country snapshots are saved after discovery and each website check. Exports are replaced atomically. Run errors remain visible in `data/state.json` and fail the GitHub job after checkpoint data is committed. There are no requests for availability or room rates.

## Sources and reuse

© [OpenStreetMap contributors](https://www.openstreetmap.org/copyright), ODbL 1.0; GeoNames, CC BY 4.0; Atout France via data.gouv.fr, Licence Ouverte 2.0. Google listing data and hotel website assertions retain their source rights; the scraper's MIT licence covers its software, not Google's data. Only required hotel fields and short room evidence are retained. Matchable properties across sources are linked by exact normalized name plus close coordinates or matching street and postcode. Raw source identities remain in separate snapshots; uncertain duplicates need review.

The public [Overpass service](https://dev.overpass-api.de/overpass-doc/en/preface/commons.html) is shared infrastructure: one query per country during the weekly full European pass, no parallel crawling, no attempts to bypass rate limits or access restrictions. Availability is not guaranteed. For a substantially larger workload, use country extracts or your own infrastructure. Collection code is MIT licensed; source data has the separate terms above.
