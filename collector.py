"""Free, serial European hotel inventory. Python 3.11+, no external dependencies."""
import argparse
import csv
from contextlib import closing
import datetime as dt
import difflib
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
               source_url=source, source_updated_at=element.get("timestamp", ""), first_seen=timestamp, last_seen=timestamp)
    row["address"] = ", ".join(filter(None, [" ".join(filter(None, [row["street"], row["house_number"]])), " ".join(filter(None, [row["postcode"], row["city"]])), country]))
    return row


def discover(country, endpoint):
    query = f'[out:json][timeout:180];area["ISO3166-1"="{country}"][admin_level=2]->.a;nwr(area.a)[tourism=hotel];out center meta;'
    raw, _ = fetch(endpoint, urllib.parse.urlencode({"data": query}).encode(), limit=80000000, timeout=220)
    result = json.loads(raw)
    if result.get("remark") or not isinstance(result.get("elements"), list):
        raise ValueError(result.get("remark", "Incomplete Overpass response"))
    timestamp = now()
    rows = [r for e in result["elements"] if (r := normalize_osm(e, country, timestamp))]
    if not rows:
        raise ValueError("Empty country result requires review; prior snapshot retained")
    return rows


def merge(old, incoming):
    """Preserve website findings and history when the source is refreshed."""
    result = dict(incoming)
    for key in ("first_seen", "last_website_check", "website_check_status"):
        result[key] = old.get(key) or result.get(key, "")
    if old.get("rooms_status") == "website_structured_reported":
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
        if found:
            count, evidence = found
            row.update(rooms=count, rooms_status="website_structured_reported", rooms_source_url=final,
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


def export(root):
    rows = []
    for file in sorted((root / "data/countries").glob("*.json")):
        rows.extend(json.loads(file.read_text(encoding="utf-8")))
    rows.sort(key=lambda r: (r["country"], r["name"], r["hotel_id"]))
    # Flag likely duplicate OSM objects, preserving all source identities for review.
    buckets = {}
    for row in rows:
        key = (row["country"], normalized(row["name"]))
        if row["name"]:
            for other in buckets.get(key, []):
                if abs(row["latitude"] - other["latitude"]) < .0005 and abs(row["longitude"] - other["longitude"]) < .0005:
                    row["duplicate_candidate"] = other["hotel_id"]
                    break
            buckets.setdefault(key, []).append(row)
    out = root / "exports"
    out.mkdir(exist_ok=True)
    for filename, subset in (("hotels.csv", rows), ("hotels-with-rooms.csv", [r for r in rows if r.get("rooms")])):
        tmp = out / (filename + ".tmp")
        with tmp.open("w", newline="", encoding="utf-8-sig") as file:
            writer = csv.DictWriter(file, FIELDS, extrasaction="ignore")
            writer.writeheader()
            writer.writerows({k: csv_safe(r.get(k)) for k in FIELDS} for r in subset)
        os.replace(tmp, out / filename)
    counts = {}
    for country in SCOPE["countries"]:
        subset = [r for r in rows if r["country"] == country]
        counts[country] = {"hotels": len(subset), "with_rooms": sum(bool(r.get("rooms")) for r in subset)}
    atomic_json(out / "coverage.json", {"updated_at": now(), "rows": len(rows), "with_rooms": sum(bool(r.get("rooms")) for r in rows),
                "duplicate_candidates": sum(bool(r.get("duplicate_candidate")) for r in rows), "countries": counts,
                "complete_europe_census": False, "license": "OSM-derived database: ODbL 1.0; website assertions retain source rights"})
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
    atomic_json(root / "exports/hotels.geojson", {"type": "FeatureCollection", "features": [{"type": "Feature", "id": r["hotel_id"], "geometry": {"type": "Point", "coordinates": [r["longitude"], r["latitude"]]}, "properties": r} for r in rows]})


def run(args):
    root = args.root
    (root / "data/countries").mkdir(parents=True, exist_ok=True)
    state_file = root / "data/state.json"
    state = json.loads(state_file.read_text()) if state_file.exists() else {"next_country_index": 0, "runs": []}
    failed = False
    if not args.export_only:
        country = args.country or SCOPE["countries"][state["next_country_index"] % len(SCOPE["countries"]) ]
        path = root / f"data/countries/{country}.json"
        started = now()
        try:
            incoming = discover(country, args.endpoint)
            previous = {r["hotel_id"]: r for r in json.loads(path.read_text(encoding="utf-8"))} if path.exists() else {}
            rows = [merge(previous[r["hotel_id"]], r) if r["hotel_id"] in previous else r for r in incoming]
            # Missing source records are retained and marked for review, never silently closed.
            present = {r["hotel_id"] for r in incoming}
            rows.extend({**r, "website_check_status": "not_in_latest_osm_snapshot"} for key, r in previous.items() if key not in present)
            atomic_json(path, rows)
            if not args.country:
                state["next_country_index"] = (state["next_country_index"] + 1) % len(SCOPE["countries"])
            state["runs"].append({"country": country, "started": started, "finished": now(), "status": "success", "hotels": len(incoming)})
            print(f"{country}: {len(incoming)} hotels collected", flush=True)
        except Exception as exc:
            failed = True
            state["runs"].append({"country": country, "started": started, "finished": now(), "status": "failed", "error": str(exc)[:500]})
            print(f"{country}: discovery failed; cursor and prior data retained: {exc}", flush=True)
        state["runs"] = state["runs"][-200:]
        atomic_json(state_file, state)
        # Fair global queue, so Germany can still gain room counts while later countries are collected.
        files = {}
        for file in sorted((root / "data/countries").glob("*.json")):
            files[file] = json.loads(file.read_text(encoding="utf-8"))
        queue = [(file, row) for file, rows in files.items() for row in rows if row.get("website") and (not row.get("last_website_check") or (dt.datetime.now(dt.timezone.utc) - dt.datetime.fromisoformat(row["last_website_check"])).days >= 90)]
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
    parser.add_argument("--export-only", action="store_true")
    parser.add_argument("--database", action="store_true")
    raise SystemExit(run(parser.parse_args()))
