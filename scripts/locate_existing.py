"""Resolve missing hotel points using existing structured addresses."""
import json
import math
import os
import time
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import urlopen

def usable(row):
    try:
        lat, lon = float(row["latitude"]), float(row["longitude"])
        return math.isfinite(lat) and math.isfinite(lon) and abs(lat)<=90 and abs(lon)<=180 and (lat,lon)!=(0,0)
    except (KeyError, TypeError, ValueError):
        return False

def main():
    key = os.environ["GEOAPIFY_API_KEY"]
    remaining = 150
    for folder in ("countries", "registries", "google"):
        for path in sorted((Path("data") / folder).glob("*.json")):
            rows = json.loads(path.read_text())
            changed = False
            for row in rows:
                if usable(row) or not remaining:
                    continue
                address = [str(row.get(k) or "").strip() for k in ("street","house_number","postcode","city","country")]
                street, number, postcode, city, country = address
                if not (street and number and city and len(country)==2) or row.get("geocode_address")==address:
                    continue
                query = urlencode(dict(street=street,housenumber=number,city=city,postcode=postcode,filter="countrycode:"+country.lower(),limit=1,format="json",apiKey=key))
                try:
                    with urlopen("https://api.geoapify.com/v1/geocode/search?"+query,timeout=20) as response:
                        hits = json.load(response)["results"]
                except Exception:
                    raise SystemExit("Geocoding service unavailable; retry the batch later") from None
                remaining -= 1
                row["geocode_address"] = address
                row["geocode_status"] = "needs_review"
                if hits:
                    hit=hits[0]
                    point=dict(latitude=hit.get("lat"),longitude=hit.get("lon"))
                    if (usable(point) and hit.get("country_code","").upper()==country.upper() and hit.get("result_type")=="building" and str(hit.get("housenumber","")).casefold()==number.casefold() and hit.get("rank",{}).get("confidence",0)>=0.9):
                        row.update(point,geocode_status="matched",geocode_source="Geoapify")
                changed=True
                time.sleep(0.25)
            if changed:
                tmp=path.with_suffix(".tmp")
                tmp.write_text(json.dumps(rows,ensure_ascii=False,indent=2)+"\n")
                tmp.replace(path)
            if not remaining:
                return

if __name__=="__main__":
    main()
