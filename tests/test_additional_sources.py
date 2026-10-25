import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import additional_sources as a
import collector as c


class AdditionalSourcesTests(unittest.TestCase):
    def test_registry_rooms_not_people_or_camping_capacity(self):
        item = {"TYPOLOGIE ÉTABLISSEMENT": "HÔTEL DE TOURISME", "NOM COMMERCIAL": "Example Hotel", "CODE POSTAL": "01230",
                "ADRESSE": "1 Rue Exemple", "COMMUNE": "Test", "NOMBRE DE CHAMBRES": "37", "CAPACITÉ D'ACCUEIL (PERSONNES)": 62}
        row = a.registry_record(item, c.now())
        self.assertEqual(row["rooms"], 37)
        self.assertEqual(row["postcode"], "01230")
        item["NOMBRE DE CHAMBRES"] = "-"
        self.assertIsNone(a.registry_record(item, c.now())["rooms"])
        item["TYPOLOGIE ÉTABLISSEMENT"] = "CAMPING"
        self.assertIsNone(a.registry_record(item, c.now()))

    def test_google_excludes_reviews_and_non_hotels(self):
        item = {"title": "Example Hotel", "category": "Hotel", "link": "https://www.google.com/maps/place/example", "place_id": "example",
                "complete_address": json.dumps({"country": "DE", "city": "Berlin"}), "review_count": "500", "review_rating": "4.9", "rooms": "999",
                "latitude": "52.5", "longitude": "13.4"}
        row = a.google_record(item, "DE", {"DE": "Germany"}, c.now())
        self.assertIsNone(row["rooms"])
        self.assertEqual(row["google_maps_url"], item["link"])
        self.assertIsNone(a.google_record(item, "FR", {"DE": "Germany"}, c.now()))
        item["category"] = "Restaurant"
        self.assertIsNone(a.google_record(item, "DE", {}, c.now()))

    def test_cross_source_merge_retains_evidence_and_conflict(self):
        row = dict.fromkeys(c.FIELDS, "")
        row.update(hotel_id="osm:node:1", name="Example Hotel", country="DE", latitude=52.5, longitude=13.4,
                   rooms=40, rooms_source_url="https://www.openstreetmap.org/node/1", source_url="https://www.openstreetmap.org/node/1")
        other = {**row, "hotel_id": "google:1", "rooms": 50, "rooms_source_url": "https://example.com", "google_maps_url": "https://www.google.com/maps/place/example"}
        result = c.merge_sources([row, other])
        self.assertEqual(len(result), 1)
        self.assertIn("review required", result[0]["rooms_conflict"])
        self.assertTrue(result[0]["google_maps_url"])

    def test_explicit_text_room_total_requires_property_identity(self):
        page = c.Page()
        page.feed('<h1>Vaduzerhof by b_smart</h1><p>35 Zimmer in Vaduzerhof by b_smart</p>')
        self.assertEqual(c.extract_text_total(page, {"name": "Hotel Vaduzerhof"})[0], 35)
        self.assertIsNone(c.extract_text_total(page, {"name": "Another Hotel"}))
        page = c.Page()
        page.feed('<h1>Vaduzerhof</h1><p>Number of beds: 68. 3 meeting rooms.</p>')
        self.assertIsNone(c.extract_text_total(page, {"name": "Hotel Vaduzerhof"}))

    def test_no_coordinates_keeps_registry_in_csv_but_not_map(self):
        with tempfile.TemporaryDirectory(dir=c.ROOT) as directory:
            root = Path(directory)
            row = a.registry_record({"TYPOLOGIE ÉTABLISSEMENT": "HÔTEL DE TOURISME", "NOM COMMERCIAL": "Example", "CODE POSTAL": "75001", "NOMBRE DE CHAMBRES": "20"}, c.now())
            c.atomic_json(root / "data/registries/FR-atout.json", [row])
            rows = c.export(root)
            c.database_export(root, rows)
            self.assertEqual(len(rows), 1)
            self.assertEqual(json.loads((root / "exports/hotels.geojson").read_text())["features"], [])

    def test_incomplete_registry_does_not_overwrite_snapshot(self):
        with tempfile.TemporaryDirectory(dir=c.ROOT) as directory:
            root = Path(directory)
            path = root / "data/registries/FR-atout.json"
            c.atomic_json(path, [{"hotel_id": "existing"}])
            with patch.object(a, "fetch", return_value=(json.dumps({"meta": {"total": 3}, "data": [], "links": {}}), "")):
                with self.assertRaises(ValueError):
                    a.france(root)
            self.assertEqual(json.loads(path.read_text()), [{"hotel_id": "existing"}])
