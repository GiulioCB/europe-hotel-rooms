"""Free, serial European hotel inventory. Python 3.11+, no external dependencies."""
import argparse
import csv
from contextlib import closing
import datetime as dt
import difflib
import gzip
import hashlib
import html
from html.parser import HTMLParser
import ipaddress
import json
import os
from pathlib import Path
import re
import socket
import sqlite3
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
import urllib.robotparser

ROOT = Path(__file__).resolve().parent
SCOPE = json.loads((ROOT / "scope.json").read_text())
AGENT = "EuropeHotelRooms/1.0 (+https://github.com/GiulioCB/europe-hotel-rooms)"
FIELDS = "hotel_id name country country_scope brand operator street house_number postcode city region address latitude longitude rooms rooms_status rooms_source_url rooms_evidence rooms_observed_at website source_url source_updated_at first_seen last_seen last_website_check website_check_status duplicate_candidate".split()
FIELDS += "source google_maps_url country_basis source_urls rooms_conflict".split()


def now():
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def positive_int(value):
    if isinstance(value, bool):
        return None
    text = str(value).strip()
    return int(text) if re.fullmatch(r"[0-9]{1,6}", text) and 0 < int(text) <= 100000 else None


def normalized(text):
    return " ".join(re.findall(r"\w+", unicodedata.normalize("NFKC", text or "").casefold()))


def public_url(url):
    """Do not let source-supplied URLs access local or private network resources."""
    u = urllib.parse.urlsplit(url)
    if u.scheme not in ("https", "http") or not u.hostname or u.username or u.password or u.port not in (None, 80, 443):
        raise ValueError("Only public HTTP(S) websites are allowed")
    addresses = socket.getaddrinfo(u.hostname, u.port or (443 if u.scheme == "https" else 80))
    if not addresses or any(not ipaddress.ip_address(x[4][0]).is_global for x in addresses):
        raise ValueError("Non-public website address")
    return url


class Redirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        public_url(newurl)
        if getattr(req, "same_host", False) and urllib.parse.urlsplit(req.full_url).netloc != urllib.parse.urlsplit(newurl).netloc:
            raise ValueError("Cross-host redirect requires a separate robots review")
        redirected = super().redirect_request(req, fp, code, msg, headers, newurl)
        if redirected:
            redirected.same_host = getattr(req, "same_host", False)
        return redirected


OPENER = urllib.request.build_opener(Redirects())


def fetch(url, data=None, limit=6000000, timeout=30, same_host=False):
    public_url(url)
    request = urllib.request.Request(url, data=data, headers={"User-Agent": AGENT, "Accept": "text/html,application/json,text/plain"})
    request.same_host = same_host
    with OPENER.open(request, timeout=timeout) as response:
        body = response.read(limit + 1)
        if len(body) > limit:
            raise ValueError("Source response exceeds size budget")
        return body.decode(response.headers.get_content_charset() or "utf-8", errors="replace"), response.url


def atomic_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def normalize_osm(element, country, timestamp):
    tags = element.get("tags", {})
    if tags.get("tourism") != "hotel":
        return None
    center = element.get("center", element)
    lat, lon = center.get("lat"), center.get("lon")
    if not isinstance(lat, (float, int)) or not isinstance(lon, (float, int)) or not -90 <= lat <= 90 or not -180 <= lon <= 180:
        return None
    row = dict.fromkeys(FIELDS, "")
    source = f"https://www.openstreetmap.org/{element['type']}/{element['id']}"
    rooms = positive_int(tags.get("rooms"))
    row.update(hotel_id=f"osm:{element['type']}:{element['id']}", name=tags.get("name") or tags.get("name:en") or "",
               country=country, country_scope="full_transcontinental_country" if country in SCOPE["transcontinental_or_boundary_scope"] else "country",
               brand=tags.get("brand", ""), operator=tags.get("operator", ""),
               street=tags.get("addr:street", ""), house_number=tags.get("addr:housenumber", ""),
               postcode=tags.get("addr:postcode", ""), city=tags.get("addr:city") or tags.get("addr:town") or tags.get("addr:village", ""),
               region=tags.get("addr:state", ""), latitude=lat, longitude=lon, rooms=rooms,
               rooms_status="community_reported" if rooms else "unknown",
               rooms_source_url=source if rooms else "", rooms_evidence=f"OSM rooms={tags['rooms']}" if rooms else "",
               rooms_observed_at=timestamp if rooms else "", website=tags.get("website") or tags.get("contact:website", ""),
               source_url=source, source="OpenStreetMap", country_basis="OSM country area membership", source_updated_at=element.get("timestamp", ""), first_seen=timestamp, last_seen=timestamp)
    row["address"] = ", ".join(filter(None, [" ".join(filter(None, [row["street"], row["house_number"]])), " ".join(filter(None, [row["postcode"], row["city"]])), country]))
    return row


def discover(country, endpoint):
    query = f'[out:json][timeout:180];area["ISO3166-1"="{country}"]->.a;.a out ids;nwr(area.a)[tourism=hotel];out center meta;'
    raw, _ = fetch(endpoint, urllib.parse.urlencode({"data": query}).encode(), limit=80000000, timeout=220)
    result = json.loads(raw)
    if result.get("remark") or not isinstance(result.get("elements"), list):
        raise ValueError(result.get("remark", "Incomplete Overpass response"))
    if not any(e.get("type") == "area" for e in result["elements"]):
        raise ValueError("Country boundary not resolved; prior snapshot and cursor retained")
    timestamp = now()
    rows = [r for e in result["elements"] if (r := normalize_osm(e, country, timestamp))]
    return rows


def merge(old, incoming):
    """Preserve website findings and history when the source is refreshed."""
    result = dict(incoming)
    for key in ("first_seen", "last_website_check", "website_check_status"):
        result[key] = old.get(key) or result.get(key, "")
    if old.get("rooms_status", "").startswith("website_"):
        for key in ("rooms", "rooms_status", "rooms_source_url", "rooms_evidence", "rooms_observed_at"):
            result[key] = old.get(key, "")
    return result


class Page(HTMLParser):
    def __init__(self):
        super().__init__()
        self.json_scripts, self.links, self.text = [], [], []
        self.in_json = False
        self.hidden = 0
        self.buffer = []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag in ("script", "style"):
            self.hidden += 1
        if tag == "script" and a.get("type", "").lower() == "application/ld+json":
            self.in_json = True
            self.buffer = []
        if tag == "a" and a.get("href"):
            self.links.append(a["href"])

    def handle_data(self, data):
        if self.in_json:
            self.buffer.append(data)
        if not self.hidden:
            self.text.append(data)

    def handle_endtag(self, tag):
        if tag == "script" and self.in_json:
            self.json_scripts.append("".join(self.buffer))
            self.in_json = False
        if tag in ("script", "style"):
            self.hidden = max(0, self.hidden - 1)


def walk(value):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from walk(child)
    elif isinstance(value, list):
        for child in value:
            yield from walk(child)


def extract_rooms(page, row):
    """Only an identity-matched Hotel object may supply an automatic total."""
    candidates = []
    for script in page.json_scripts:
        try:
            parsed = json.loads(html.unescape(script))
        except ValueError:
            continue
        for obj in walk(parsed):
            kinds = obj.get("@type", [])
            kinds = [kinds] if isinstance(kinds, str) else kinds
            if not isinstance(kinds, list) or not any(str(k).split("/")[-1] == "Hotel" for k in kinds):
                continue
            name = obj.get("name")
            if not isinstance(name, str) or not row.get("name"):
                continue
            similarity = difflib.SequenceMatcher(None, normalized(name), normalized(row["name"])).ratio()
            address = obj.get("address")
            postcode = address.get("postalCode") if isinstance(address, dict) else None
            if similarity < 0.9 or (postcode and row.get("postcode") and normalized(str(postcode)) != normalized(row["postcode"])):
                continue
            value = obj.get("numberOfRooms")
            if isinstance(value, dict):
                # Do not accept per-room, double-room or suite category counts.
                if value.get("unitText") or value.get("name") or value.get("minValue") or value.get("maxValue"):
                    continue
                value = value.get("value")
            count = positive_int(value)
            if count:
                candidates.append((count, json.dumps({"@type": "Hotel", "name": name, "numberOfRooms": obj["numberOfRooms"]}, ensure_ascii=False)))
    if len({c[0] for c in candidates}) == 1:
        return candidates[0]
    return None


def extract_text_total(page, row):
    text = " ".join(" ".join(page.text).split())
    identity = re.sub(r"^(?:hotel|hôtel)\s+", "", normalized(row.get("name")), flags=re.I)
    if len(identity) < 8 or identity not in normalized(text[:6000]):
        return None
    patterns = [r"(?:total number of rooms|number of guest rooms|anzahl (?:der )?zimmer|nombre total de chambres)\s*[:|]?\s*(\d{1,5})\b",
                r"(?:our hotel|the hotel)\s+(?:has|offers|features|comprises)\s+(\d{1,5})\s+(?:guest\s+)?rooms\b",
                r"unser hotel\s+verfügt über\s+(\d{1,5})\s+zimmer\b",
                r"\b(\d{1,5})\s+(?:rooms|zimmer|chambres)\s+(?:in|at|im|dans)\s+" + re.escape(identity)]
    found = []
    for pattern in patterns:
        for match in re.finditer(pattern, text, re.I):
            excerpt = text[max(0, match.start() - 60):match.end() + 60]
            if re.search(r"conference|meeting|event|banquet|konferenz|tagungs", excerpt, re.I):
                continue
            count = positive_int(match.group(1))
            if count:
                found.append((count, excerpt))
    return found[0] if len({r[0] for r in found}) == 1 else None


def enrich(row, delay=5):
    url = row["website"]
    if not urllib.parse.urlsplit(url).scheme:
        url = "https://" + url
    public_url(url)
    origin = urllib.parse.urlsplit(url)
    robots_url = urllib.parse.urlunsplit((origin.scheme, origin.netloc, "/robots.txt", "", ""))
    robot = urllib.robotparser.RobotFileParser()
    try:
        robots, _ = fetch(robots_url, limit=1000000, same_host=True)
        robot.parse(robots.splitlines())
    except urllib.error.HTTPError as exc:
        if exc.code not in (404, 410):
            raise
        robot.parse([])
    crawl_delay = robot.crawl_delay(AGENT) or robot.crawl_delay("*") or 0
    wait = max(delay, crawl_delay)
    if wait > 60:
        raise ValueError("Site crawl delay exceeds this run's request budget")
    queue, seen = [url], set()
    while queue and len(seen) < 3:
        current = queue.pop(0)
        if current in seen:
            continue
        seen.add(current)
        if not robot.can_fetch(AGENT, current):
            row["website_check_status"] = "robots_disallowed"
            continue
        time.sleep(wait)
        text, final = fetch(current, same_host=True)
        # A redirect to another host needs a separate robots check on a future run.
        if urllib.parse.urlsplit(final).netloc != origin.netloc:
            row["website_check_status"] = "redirect_requires_review"
            continue
        page = Page()
        page.feed(text)
        found = extract_rooms(page, row)
        status = "website_structured_reported"
        if not found:
            found = extract_text_total(page, row)
            status = "website_text_reported"
        if found:
            count, evidence = found
            row.update(rooms=count, rooms_status=status, rooms_source_url=final,
                       rooms_evidence=evidence, rooms_observed_at=now(), website_check_status="rooms_found")
            return
        for link in page.links:
            absolute = urllib.parse.urljoin(final, link).split("#")[0]
            parts = urllib.parse.urlsplit(absolute)
            if parts.netloc == origin.netloc and re.search(r"about|facts|ueber|uber-uns|unser-hotel|hotel-info", parts.path, re.I) and absolute not in seen:
                queue.append(absolute)
        row["website_check_status"] = "no_matching_structured_total"


def csv_safe(value):
    if isinstance(value, str) and value.lstrip().startswith(("=", "+", "-", "@", "\t", "\r")):
        return "'" + value
    return value


def write_csv(path, rows, compressed=False):
    tmp = path.with_suffix(path.suffix + ".tmp")
    opener = gzip.open if compressed else open
    with opener(tmp, "wt", newline="", encoding="utf-8-sig") as file:
        writer = csv.DictWriter(file, FIELDS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows({k: csv_safe(r.get(k)) for k in FIELDS} for r in rows)
    os.replace(tmp, path)


def has_coordinates(row):
    return isinstance(row.get("latitude"), (int, float)) and isinstance(row.get("longitude"), (int, float))


def merge_sources(rows):
    """Link exact property names only when coordinates or street/postcode agree."""
    groups, merged = {}, []
    for row in rows:
        key = (row["country"], normalized(row["name"]))
        match = None
        for previous in groups.get(key, []):
            if row["hotel_id"].split(":", 1)[0] == previous["hotel_id"].split(":", 1)[0]:
                continue
            near = has_coordinates(row) and has_coordinates(previous) and abs(row["latitude"] - previous["latitude"]) < .0007 and abs(row["longitude"] - previous["longitude"]) < .0007
            street_match = row.get("street") and row.get("postcode") and normalized(row["street"]) == normalized(previous.get("street")) and row["postcode"] == previous.get("postcode")
            if near or street_match:
                match = previous
                break
        if match is None or not row["name"]:
            row["source_urls"] = row.get("source_urls") or row.get("source_url", "")
            groups.setdefault(key, []).append(row)
            merged.append(row)
            continue
        links = set(filter(None, (match.get("source_urls", "") + " | " + row.get("source_url", "")).split(" | ")))
        match["source_urls"] = " | ".join(sorted(links))
        for field in ("google_maps_url", "website", "brand", "street", "city", "postcode", "address"):
            if not match.get(field) and row.get(field):
                match[field] = row[field]
        if not has_coordinates(match) and has_coordinates(row):
            match["latitude"], match["longitude"] = row["latitude"], row["longitude"]
        if row.get("rooms") and match.get("rooms") and row["rooms"] != match["rooms"]:
            match["rooms_conflict"] = f"{match['rooms']} ({match.get('rooms_source_url')}) versus {row['rooms']} ({row.get('rooms_source_url')}); review required"
        if row.get("rooms") and not match.get("rooms"):
            for field in ("rooms", "rooms_status", "rooms_source_url", "rooms_evidence", "rooms_observed_at"):
                match[field] = row.get(field)
    return merged


def export(root):
    rows = []
    for file in sorted((root / "data/countries").glob("*.json")):
        rows.extend(json.loads(file.read_text(encoding="utf-8")))
    for source in ("google", "registries"):
        for file in sorted((root / "data" / source).glob("*.json")):
            rows.extend(json.loads(file.read_text(encoding="utf-8")))
    identities = {}
    for row in rows:
        old = identities.get(row["hotel_id"])
        quality = lambda r: (r.get("country_scope") != "query_country_unverified", r.get("source_updated_at", ""), r.get("last_seen", ""))
        if old is None or quality(row) > quality(old):
            identities[row["hotel_id"]] = row
    rows = list(identities.values())
    rows = merge_sources(rows)
    rows.sort(key=lambda r: (r["country"], r["name"], r["hotel_id"]))
    # Flag likely duplicate OSM objects, preserving all source identities for review.
    buckets = {}
    for row in rows:
        key = (row["country"], normalized(row["name"]))
        if row["name"]:
            for other in buckets.get(key, []):
                if has_coordinates(row) and has_coordinates(other) and abs(row["latitude"] - other["latitude"]) < .0005 and abs(row["longitude"] - other["longitude"]) < .0005:
                    row["duplicate_candidate"] = other["hotel_id"]
                    break
            buckets.setdefault(key, []).append(row)
    out = root / "exports"
    out.mkdir(exist_ok=True)
    for filename, subset in (("hotels.csv", rows), ("hotels-with-rooms.csv", [r for r in rows if r.get("rooms")])):
        write_csv(out / filename, subset)
        write_csv(out / (filename + ".gz"), subset, compressed=True)
        # GitHub rejects files over 100 MiB. Keep the full compressed download
        # and country parts when an uncompressed combined file grows too large.
        if (out / filename).stat().st_size > 85 * 1024 * 1024:
            (out / filename).unlink()
    parts = out / "countries"
    parts.mkdir(exist_ok=True)
    part_names = set()
    counts = {}
    for country in SCOPE["countries"]:
        subset = [r for r in rows if r["country"] == country]
        for start in range(0, len(subset), 10000):
            filename = f"{country}-{start // 10000 + 1:03d}.csv"
            write_csv(parts / filename, subset[start:start + 10000])
            part_names.add(filename)
        counts[country] = {"hotels": len(subset), "with_rooms": sum(bool(r.get("rooms")) for r in subset),
                           "source_last_seen": max((r.get("last_seen", "") for r in subset), default=None)}
    for file in parts.glob("*.csv"):
        if file.name not in part_names:
            file.unlink()
    state_path = root / "data/state.json"
    state = json.loads(state_path.read_text()) if state_path.exists() else {}
    atomic_json(out / "coverage.json", {"updated_at": now(), "rows": len(rows), "with_rooms": sum(bool(r.get("rooms")) for r in rows),
                "duplicate_candidates": sum(bool(r.get("duplicate_candidate")) for r in rows), "countries": counts,
                "latest_pass": state.get("latest_pass"), "combined_csv_available": (out / "hotels.csv").exists(),
                "additional_sources": [json.loads(file.read_text(encoding="utf-8")) for file in sorted((root / "data/source-coverage").glob("*.json"))],
                "complete_europe_census": False, "license": "OSM: ODbL; Atout France: Licence Ouverte; Google and website assertions retain source rights"})
    # Database and GeoJSON are local on-demand exports to avoid binary Git history growth.
    return rows


def database_export(root, rows):
    path = root / "exports/hotels.sqlite"
    with closing(sqlite3.connect(path)) as db, db:
        db.execute("DROP TABLE IF EXISTS hotels")
        db.execute("CREATE TABLE hotels (" + ",".join(f'"{k}" ' + ("INTEGER" if k == "rooms" else "REAL" if k in ("latitude", "longitude") else "TEXT") for k in FIELDS) + ", PRIMARY KEY(hotel_id))")
        db.executemany("INSERT INTO hotels VALUES(" + ",".join("?" for _ in FIELDS) + ")", [[r.get(k) for k in FIELDS] for r in rows])
        db.execute("CREATE INDEX hotel_country ON hotels(country)")
        db.execute("CREATE INDEX hotel_rooms ON hotels(rooms)")
    atomic_json(root / "exports/hotels.geojson", {"type": "FeatureCollection", "features": [{"type": "Feature", "id": r["hotel_id"], "geometry": {"type": "Point", "coordinates": [r["longitude"], r["latitude"]]}, "properties": r} for r in rows if has_coordinates(r)]})


def run(args):
    root = args.root
    (root / "data/countries").mkdir(parents=True, exist_ok=True)
    state_file = root / "data/state.json"
    state = json.loads(state_file.read_text()) if state_file.exists() else {"runs": []}
    failed = False
    if not args.export_only:
        countries = [args.country] if args.country else SCOPE["countries"]
        state.pop("next_country_index", None)
        previous_pass = state.get("latest_pass", {})
        resume = not args.country and previous_pass.get("scope") == "all_europe" and previous_pass.get("pending") and (dt.datetime.now(dt.timezone.utc) - dt.datetime.fromisoformat(previous_pass["started"])).total_seconds() < 86400
        if resume:
            countries = list(dict.fromkeys(previous_pass["pending"] + previous_pass.get("failed", [])))
        report = {"started": now(), "scope": "single_country" if args.country else "all_europe",
                  "expected_countries": [args.country] if args.country else SCOPE["countries"],
                  "succeeded": list(previous_pass.get("succeeded", [])) if resume else [], "failed": [], "pending": list(countries), "complete": False}
        state["latest_pass"] = report
        atomic_json(state_file, state)
        for index, country in enumerate(countries):
            if index:
                time.sleep(getattr(args, "country_delay", 15))
            path = root / f"data/countries/{country}.json"
            started = now()
            try:
                incoming = discover(country, args.endpoint)
                previous = {r["hotel_id"]: r for r in json.loads(path.read_text(encoding="utf-8"))} if path.exists() else {}
                rows = [merge(previous[r["hotel_id"]], r) if r["hotel_id"] in previous else r for r in incoming]
                present = {r["hotel_id"] for r in incoming}
                rows.extend({**r, "website_check_status": "not_in_latest_osm_snapshot"} for key, r in previous.items() if key not in present)
                atomic_json(path, rows)
                report["succeeded"].append(country)
                state["runs"].append({"country": country, "started": started, "finished": now(), "status": "success", "hotels": len(incoming)})
                print(f"{country}: {len(incoming)} hotels collected ({index + 1}/{len(countries)})", flush=True)
            except Exception as exc:
                failed = True
                report["failed"].append(country)
                state["runs"].append({"country": country, "started": started, "finished": now(), "status": "failed", "error": str(exc)[:500]})
                print(f"{country}: discovery failed; prior data retained; continuing with remaining countries: {exc}", flush=True)
            report["pending"].remove(country)
            state["runs"] = state["runs"][-200:]
            atomic_json(state_file, state)
        report.update(finished=now(), complete=not failed)
        atomic_json(state_file, state)
        # Fair website queue is separate from the weekly refresh of every country.
        files = {}
        for source in ("countries", "google", "registries"):
            for file in sorted((root / "data" / source).glob("*.json")):
                files[file] = json.loads(file.read_text(encoding="utf-8"))
        queue = [(file, row) for file, rows in files.items() for row in rows if row.get("website") and (not row.get("last_website_check") or (dt.datetime.now(dt.timezone.utc) - dt.datetime.fromisoformat(row["last_website_check"])).days >= 7)]
        queue.sort(key=lambda item: (item[1].get("last_website_check", ""), item[1]["country"] != country, bool(item[1].get("rooms")), item[1]["hotel_id"]))
        deadline = time.monotonic() + args.minutes * 60
        for file, row in queue[:args.enrich_limit]:
            if time.monotonic() >= deadline:
                break
            try:
                enrich(row, args.delay)
            except Exception as exc:
                row["website_check_status"] = "error: " + str(exc)[:180]
            row["last_website_check"] = now()
            atomic_json(file, files[file])
            print(f"Website checked: {row['hotel_id']} / {row['website_check_status']}", flush=True)
    rows = export(root)
    if args.database:
        database_export(root, rows)
    print(f"Exported {len(rows)} hotels; {sum(bool(r.get('rooms')) for r in rows)} with sourced room totals", flush=True)
    return 1 if failed else 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--country", choices=SCOPE["countries"])
    parser.add_argument("--endpoint", default="https://overpass-api.de/api/interpreter")
    parser.add_argument("--enrich-limit", type=int, default=200)
    parser.add_argument("--minutes", type=float, default=35)
    parser.add_argument("--delay", type=float, default=5)
    parser.add_argument("--country-delay", type=float, default=15)
    parser.add_argument("--export-only", action="store_true")
    parser.add_argument("--database", action="store_true")
    raise SystemExit(run(parser.parse_args()))
