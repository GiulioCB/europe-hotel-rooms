import argparse
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import collector as c


def hotel(**tags):
    return c.normalize_osm({"type": "node", "id": 42, "lat": 52.5, "lon": 13.4,
                            "tags": {"tourism": "hotel", "name": "Hotel Example", **tags}}, "DE", "2026-10-25T00:00:00+00:00")


class CollectorTests(unittest.TestCase):
    def test_independent_hotels_and_unknown_rooms(self):
        row = hotel(beds="80", capacity="100")
        self.assertEqual(row["name"], "Hotel Example")
        self.assertEqual(row["brand"], "")
        self.assertIsNone(row["rooms"])
        self.assertEqual(row["rooms_status"], "unknown")

    def test_rooms_never_beds_and_invalid_values(self):
        self.assertEqual(hotel(rooms="120", beds="240")["rooms"], 120)
        for value in ("12-15", "about 100", "0", "-2", True, "15.5"):
            self.assertIsNone(c.positive_int(value))

    def test_room_category_and_other_properties_are_rejected(self):
        page = c.Page()
        page.feed('<script type="application/ld+json">' + json.dumps([
            {"@type": "HotelRoom", "name": "Hotel Example", "numberOfRooms": 2},
            {"@type": "Hotel", "name": "Different Resort", "numberOfRooms": 400},
            {"@type": "Hotel", "name": "Hotel Example", "numberOfRooms": {"value": 50, "unitText": "double rooms"}}
        ]) + '</script>')
        self.assertIsNone(c.extract_rooms(page, hotel()))

    def test_identity_matched_structured_total(self):
        page = c.Page()
        page.feed('<script type="application/ld+json">{"@graph":[{"@type":"Hotel","name":"Hotel Example","numberOfRooms":120}]}</script>')
        self.assertEqual(c.extract_rooms(page, hotel())[0], 120)

    def test_conflicting_totals_are_rejected(self):
        page = c.Page()
        page.feed('<script type="application/ld+json">' + json.dumps([
            {"@type": "Hotel", "name": "Hotel Example", "numberOfRooms": 50},
            {"@type": "Hotel", "name": "Hotel Example", "numberOfRooms": 60}]) + '</script>')
        self.assertIsNone(c.extract_rooms(page, hotel()))

    def test_merge_preserves_website_evidence_and_first_seen(self):
        old = hotel()
        old.update(rooms=120, rooms_status="website_structured_reported", rooms_evidence="Hotel total", first_seen="2020-01-01")
        merged = c.merge(old, hotel(rooms="80"))
        self.assertEqual(merged["rooms"], 120)
        self.assertEqual(merged["rooms_evidence"], "Hotel total")
        self.assertEqual(merged["first_seen"], "2020-01-01")

    def test_failure_preserves_country_and_continues_full_pass(self):
        with tempfile.TemporaryDirectory(dir=c.ROOT) as directory:
            root = Path(directory)
            c.atomic_json(root / "data/countries/DE.json", [hotel(rooms="20")])
            args = argparse.Namespace(root=root, export_only=False, country=None, endpoint="", minutes=0, enrich_limit=0, delay=5, database=False)
            args.country_delay = 0
            with patch.dict(c.SCOPE, countries=["DE", "AT"]), patch.object(c, "discover", side_effect=[ValueError("source timeout"), []]) as discover:
                self.assertEqual(c.run(args), 1)
            self.assertEqual([call.args[0] for call in discover.call_args_list], ["DE", "AT"])
            report = json.loads((root / "data/state.json").read_text())["latest_pass"]
            self.assertEqual(report["succeeded"], ["AT"])
            self.assertEqual(report["failed"], ["DE"])
            self.assertFalse(report["complete"])
            self.assertEqual(json.loads((root / "data/countries/DE.json").read_text())[0]["rooms"], 20)

    def test_default_pass_visits_every_country_from_germany(self):
        with tempfile.TemporaryDirectory(dir=c.ROOT) as directory:
            args = argparse.Namespace(root=Path(directory), export_only=False, country=None, endpoint="", minutes=0, enrich_limit=0, delay=5, country_delay=0, database=False)
            with patch.object(c, "discover", return_value=[]) as discover:
                self.assertEqual(c.run(args), 0)
            self.assertEqual([call.args[0] for call in discover.call_args_list], c.SCOPE["countries"])
            report = json.loads((args.root / "data/state.json").read_text())["latest_pass"]
            self.assertTrue(report["complete"])
            self.assertEqual(len(report["succeeded"]), 57)

    def test_public_url_blocks_private_addresses(self):
        with patch.object(c.socket, "getaddrinfo", return_value=[(2, 1, 6, "", ("127.0.0.1", 80))]):
            with self.assertRaises(ValueError):
                c.public_url("http://localhost/test")

    def test_resolved_empty_country_can_advance(self):
        with patch.object(c, "fetch", return_value=(json.dumps({"elements": [{"type": "area", "id": 1}]}), "")):
            self.assertEqual(c.discover("VA", ""), [])
        with patch.object(c, "fetch", return_value=(json.dumps({"elements": []}), "")):
            with self.assertRaises(ValueError):
                c.discover("VA", "")

    def test_csv_formula_injection_and_exports(self):
        self.assertEqual(c.csv_safe("=HYPERLINK(\"evil\")"), "'=HYPERLINK(\"evil\")")
        with tempfile.TemporaryDirectory(dir=c.ROOT) as directory:
            root = Path(directory)
            c.atomic_json(root / "data/countries/DE.json", [hotel(rooms="20")])
            rows = c.export(root)
            c.database_export(root, rows)
            self.assertTrue((root / "exports/hotels.sqlite").exists())
            geo = json.loads((root / "exports/hotels.geojson").read_text())
            self.assertEqual(geo["features"][0]["geometry"]["coordinates"], [13.4, 52.5])


if __name__ == "__main__":
    unittest.main()
