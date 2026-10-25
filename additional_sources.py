"""Free hotel discovery from Google Maps and the French official hotel register."""
import argparse
import csv
import hashlib
import io
import json
from pathlib import Path
import subprocess
import time
import urllib.request
import zipfile

from collector import ROOT, SCOPE, FIELDS, AGENT, atomic_json, now, normalized, positive_int, fetch, merge

FR_RESOURCE = "3ce290bf-07ec-4d63-b12b-d0496193a535"
FR_API = f"https://tabular-api.data.gouv.fr/api/resources/{FR_RESOURCE}/data/"
FR_SOURCE = "https://www.data.gouv.fr/datasets/hebergements-touristiques-classes-en-france"
SCRAPER_RELEASE = "v1.18.1"
SCRAPER_FILE = "google_maps_scraper-1.18.1-linux-amd64"
SCRAPER_SHA256 = "af573eeab19b174e8a70a5c804b80f191681b2c9d01c96706691af6567926062"


def blank():
    return dict.fromkeys(FIELDS, "")


def registry_record(item, timestamp):
    if item.get("TYPOLOGIE ÉTABLISSEMENT") != "HÔTEL DE TOURISME":
        return None
    postcode = str(item.get("CODE POSTAL", "")).zfill(5)
    if postcode.startswith(("97", "98")):
        return None  # Overseas departments and separately coded territories.
    name, street = item.get("NOM COMMERCIAL", "").strip(), item.get("ADRESSE", "").strip()
    if not name:
        return None
    identity = hashlib.sha256(normalized(name + " " + street + " " + postcode).encode()).hexdigest()[:24]
    rooms = positive_int(item.get("NOMBRE DE CHAMBRES"))
    row = blank()
    row.update(hotel_id="atout:" + identity, name=name, country="FR", country_scope="country", country_basis="French classified hotel register",
               street=street, postcode=postcode, city=item.get("COMMUNE", ""),
               address=", ".join(filter(None, [street, postcode, item.get("COMMUNE"), "FR"])), latitude=None, longitude=None,
               rooms=rooms, rooms_status="registry_reported" if rooms else "unknown", rooms_source_url=FR_SOURCE if rooms else "",
               rooms_evidence=f"NOMBRE DE CHAMBRES={item.get('NOMBRE DE CHAMBRES')}" if rooms else "", rooms_observed_at=timestamp if rooms else "",
               website=item.get("SITE INTERNET", ""), source_url=FR_SOURCE, source="Atout France official register",
               first_seen=timestamp, last_seen=timestamp, source_updated_at=str(item.get("DATE DE CLASSEMENT", "")))
    return row


def france(root=ROOT):
    timestamp, items, expected = now(), [], None
    url = FR_API + "?page_size=200"
    seen = set()
    while url:
        if url in seen or not url.startswith(FR_API):
            raise ValueError("Unexpected register pagination")
        seen.add(url)
        text, _ = fetch(url, timeout=45, limit=12000000)
        payload = json.loads(text)
        if expected is None:
            expected = payload["meta"]["total"]
        if not isinstance(payload.get("data"), list) or payload["meta"]["total"] != expected:
            raise ValueError("Register changed during pagination; prior data retained")
        items.extend(payload["data"])
        url = payload.get("links", {}).get("next")
        if url:
            time.sleep(1)
    if not expected or len(items) != expected:
        raise ValueError("Incomplete national register; prior snapshot retained")
    identities = {}
    for item in items:
        row = registry_record(item, timestamp)
        if row is None:
            continue
        old = identities.get(row["hotel_id"])
        if old is None or row["source_updated_at"] > old["source_updated_at"]:
            identities[row["hotel_id"]] = row
        elif row["source_updated_at"] == old["source_updated_at"] and row["rooms"] != old["rooms"]:
            old["rooms_conflict"] = f"Register has conflicting same-date room totals: {old['rooms']} and {row['rooms']}; review required"
    rows = list(identities.values())
    if not rows:
        raise ValueError("Register schema changed or no hotel records")
    path = root / "data/registries/FR-atout.json"
    old = {r["hotel_id"]: r for r in json.loads(path.read_text(encoding="utf-8"))} if path.exists() else {}
    for row in rows:
        row["first_seen"] = old.get(row["hotel_id"], {}).get("first_seen", timestamp)
    atomic_json(path, rows)
    atomic_json(root / "data/source-coverage/FR-atout.json", {"source": FR_SOURCE, "checked_at": timestamp,
                "register_rows": len(items), "hotel_rows": len(rows), "with_rooms": sum(bool(r["rooms"]) for r in rows),
                "snapshot_download_complete": True, "all_hotels_in_country": False, "license": "Licence Ouverte 2.0"})
    print(f"Atout France: {len(rows)} hotels, {sum(bool(r['rooms']) for r in rows)} reported room totals", flush=True)


def country_names():
    text, _ = fetch("https://download.geonames.org/export/dump/countryInfo.txt", limit=1000000)
    return {parts[0]: parts[4] for line in text.splitlines() if not line.startswith("#") and len(parts := line.split("\t")) > 4}


def queries(country, names, root=ROOT, explicit_city=None):
    if explicit_city:
        return [f"hotels in {explicit_city} {names.get(country, country)}"]
    cache = root / ".cache/cities500.zip"
    cache.parent.mkdir(parents=True, exist_ok=True)
    if not cache.exists():
        with urllib.request.urlopen("https://download.geonames.org/export/dump/cities500.zip", timeout=90) as response:
            content = response.read(30000000)
        cache.write_bytes(content)
    towns = []
    with zipfile.ZipFile(cache) as archive:
        for line in archive.read("cities500.txt").decode("utf-8").splitlines():
            fields = line.split("\t")
            if len(fields) > 14 and fields[8] == country:
                towns.append((int(fields[14] or 0), fields[1], fields[10]))
    towns.sort(reverse=True)
    # All listed localities are queued, not just the capital or places in OSM.
    result = list(dict.fromkeys(f"hotels in {city} {region} {names.get(country, country)}" for _, city, region in towns))
    return result or [f"hotels in {names.get(country, country)}"]


def google_record(item, expected_country, names, timestamp):
    if "hotel" not in str(item.get("category", "")).casefold():
        return None
    name = str(item.get("title") or "").strip()
    if not name:
        return None
    address = item.get("complete_address") or {}
    if isinstance(address, str):
        try:
            address = json.loads(address)
        except ValueError:
            address = {}
    if not isinstance(address, dict):
        address = {}
    reported = str(address.get("country") or "").strip()
    reverse = {normalized(v): k for k, v in names.items()}
    code = reported.upper() if len(reported) == 2 and reported.isalpha() else reverse.get(normalized(reported))
    if code and code != expected_country:
        return None
    source_url = str(item.get("link") or "")
    if not source_url.startswith(("https://www.google.com/maps", "https://maps.google.com/")):
        return None
    identity = item.get("place_id") or item.get("cid") or hashlib.sha256(source_url.encode()).hexdigest()[:24]
    def coord(key, bound):
        try:
            number = float(item[key])
            return number if -bound <= number <= bound else None
        except (ValueError, KeyError, TypeError):
            return None
    row = blank()
    row.update(hotel_id="google:" + str(identity), name=name, country=code or expected_country,
               country_scope=("full_transcontinental_country" if code in SCOPE["transcontinental_or_boundary_scope"] else "country") if code else "query_country_unverified", country_basis="Google address country" if code else "Search query only; country needs review",
               address=str(item.get("address") or ""), street=address.get("street", ""), city=address.get("city", ""),
               postcode=str(address.get("postal_code") or ""), region=address.get("state", ""),
               latitude=coord("latitude", 90), longitude=coord("longitude", 180), rooms=None, rooms_status="unknown",
               website=str(item.get("website") or ""), source_url=source_url, google_maps_url=source_url,
               source="Google Maps listing", first_seen=timestamp, last_seen=timestamp)
    # Ratings, review counts, bed counts and capacity are never room totals.
    return row


def install_scraper(root=ROOT):
    path = root / "tools/google-maps-scraper"
    path.parent.mkdir(exist_ok=True)
    if not path.exists():
        url = f"https://github.com/gosom/google-maps-scraper/releases/download/{SCRAPER_RELEASE}/{SCRAPER_FILE}"
        with urllib.request.urlopen(url, timeout=120) as response:
            path.write_bytes(response.read(100000000))
    if hashlib.sha256(path.read_bytes()).hexdigest() != SCRAPER_SHA256:
        raise ValueError("Scraper release checksum mismatch")
    path.chmod(0o755)
    return path


def google(country, root=ROOT, minutes=22, city=None, binary=None):
    names, timestamp = country_names(), now()
    planned = queries(country, names, root, city)
    working = root / ".cache/google" / country
    working.mkdir(parents=True, exist_ok=True)
    query_file, output = working / "queries.txt", working / "results.csv"
    query_file.write_text("\n".join(planned) + "\n", encoding="utf-8")
    binary = binary or install_scraper(root)
    cmd = [str(binary.resolve()), "-input", str(query_file.resolve()), "-results", str(output.resolve()),
           "-depth", "10", "-c", "1", "-lang", "en", "-exit-on-inactivity", "1m"]
    timed_out = False
    with (working / "run.log").open("w", encoding="utf-8") as log:
        process = subprocess.Popen(cmd, stdout=log, stderr=subprocess.STDOUT)
        try:
            code = process.wait(timeout=minutes * 60)
        except subprocess.TimeoutExpired:
            timed_out = True
            process.terminate()
            try:
                code = process.wait(timeout=15)
            except subprocess.TimeoutExpired:
                process.kill()
                code = process.wait()
    collected = {}
    if output.exists():
        with output.open(encoding="utf-8-sig", newline="") as file:
            for item in csv.DictReader(file):
                row = google_record(item, country, names, timestamp)
                if row:
                    collected[row["hotel_id"]] = row
    path = root / f"data/google/{country}.json"
    old = {r["hotel_id"]: r for r in json.loads(path.read_text(encoding="utf-8"))} if path.exists() else {}
    for identity, row in collected.items():
        row["first_seen"] = old.get(identity, {}).get("first_seen", timestamp)
        old[identity] = merge(old[identity], row) if identity in old else row
    if collected:
        atomic_json(path, list(old.values()))
    report = {"country": country, "started_at": timestamp, "finished_at": now(), "planned_locality_queries": len(planned),
              "new_observations": len(collected), "retained_records": len(old), "process_exit_code": code, "time_budget_reached": timed_out,
              "source": "Google Maps via gosom/google-maps-scraper v1.18.1", "paid_api": False, "paid_proxy": False,
              "complete_hotel_census": False, "all_queries_completed": False if timed_out or code else None,
              "note": "Search result coverage is partial; a successful process does not establish exhaustive Google listings. Zero results can mean blocking. Missing totals remain unknown."}
    atomic_json(root / f"data/source-coverage/google-{country}.json", report)
    print(json.dumps(report), flush=True)
    return 0 if collected else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", choices=["france", "google"])
    parser.add_argument("--country", choices=SCOPE["countries"], default="DE")
    parser.add_argument("--city")
    parser.add_argument("--minutes", type=float, default=22)
    parser.add_argument("--binary", type=Path)
    args = parser.parse_args()
    if args.source == "france":
        france()
    else:
        raise SystemExit(google(args.country, minutes=args.minutes, city=args.city, binary=args.binary))
