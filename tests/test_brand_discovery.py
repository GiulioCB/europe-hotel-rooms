import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location('discovery', Path(__file__).parents[1] / 'scripts/discover-hotelier-brands.py')
discovery = importlib.util.module_from_spec(spec)
spec.loader.exec_module(discovery)


class DiscoveryTests(unittest.TestCase):
    def test_article_boundaries_types_aliases_and_unverified_relationships(self):
        html = '''<ul><li><a href="/nav">Navigation</a></li></ul>
        <h1>Article</h1><h2>Große Hotelketten Deutschland &amp; weltweit</h2>
        <ul><li><a href="/brand">AMERON (M)</a> Marke der <a href="/group">Althoff</a></li>
        <li><a href="https://example.org">Example</a> (BF)</li>
        <li><a href="/coop">Cooperative</a> - HKO</li>
        <li><a href="/brand">AMERON (M)</a></li></ul>
        <p>Tipps</p><ul><li><a href="/irrelevant">Unrelated</a></li></ul>'''
        rows = discovery.parse_directory(html, {'brands': [{'id': 'a', 'name': 'Ameron', 'aliases': []}]})
        self.assertEqual(len(rows), 3)
        ameron = next(r for r in rows if r['name'] == 'AMERON')
        self.assertEqual(ameron['matchedCatalogueIds'], ['a'])
        self.assertEqual(ameron['relatedSourceUrls'], ['https://www.hotelier.de/group'])
        self.assertEqual(ameron['verifiedParentIds'], [])
        self.assertEqual(ameron['verificationStatus'], 'unverified')
        self.assertEqual(next(r for r in rows if r['name'] == 'Example')['entityTypeCandidate'], 'operator')
        self.assertEqual(next(r for r in rows if r['name'] == 'Cooperative')['entityTypeCandidate'], 'cooperation')

    def test_ambiguous_aliases_and_unsafe_links(self):
        rows = discovery.parse_directory('''<h1>Article</h1><h2>Hotelketten B</h2><ul>
        <li><a href="/shared">Shared</a></li><li><a href="javascript:bad()">Bad</a></li></ul>''',
        {'brands': [{'id': 'a', 'name': 'Shared'}, {'id': 'b', 'name': 'Shared'}]})
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['reviewStatus'], 'ambiguous_name')
        self.assertEqual(discovery.safe_cell(' =SUM(A1)'), "' =SUM(A1)")


if __name__ == '__main__':
    unittest.main()
