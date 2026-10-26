"""Publish a review queue of factual directory names, never verified ownership.

One index request, robots checked, no profile crawl or paid dependencies.
"""
import argparse
import csv
import hashlib
import io
import json
import re
import unicodedata
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin, urlsplit
from urllib.request import Request, urlopen
from urllib.robotparser import RobotFileParser

SOURCE = 'https://www.hotelier.de/hotellerie/hotelgewerbe/hotelketten-deutschland-international-hotelgesellschaft-weltweit'
AGENT = 'EuropeanHotelBrandDiscovery/1.0'


def fold(value):
    value = ''.join(c for c in unicodedata.normalize('NFKD', value) if not unicodedata.combining(c))
    return re.sub(r'[^\w]+', ' ', value.lower().replace('&', ' and ').replace('+', ' plus ')).strip()


class DirectoryParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.active = False
        self.heading = None
        self.item = None
        self.anchor = None
        self.rows = []
        self.article = False

    def handle_starttag(self, tag, attrs):
        if tag == 'h1':
            self.article = True
        if tag == 'h2':
            self.heading = []
        if self.active and tag in ('p', 'h3', 'h4'):
            # The directory finishes before the tips paragraph.
            self.active = False
        if self.active and tag == 'li':
            self.item = {'text': [], 'links': []}
        if self.item is not None and tag == 'a':
            href = dict(attrs).get('href', '')
            self.anchor = {'href': href, 'text': []}

    def handle_data(self, data):
        if self.heading is not None:
            self.heading.append(data)
        if self.item is not None:
            self.item['text'].append(data)
        if self.anchor is not None:
            self.anchor['text'].append(data)

    def handle_endtag(self, tag):
        if tag == 'h2' and self.heading is not None:
            heading = ' '.join(self.heading)
            self.active = self.article and bool(re.search(r'Hotelkett(?:e|en)\b', heading))
            self.heading = None
        if tag == 'a' and self.anchor is not None:
            if self.item is not None:
                self.item['links'].append(self.anchor)
            self.anchor = None
        if tag == 'li' and self.item is not None:
            self.rows.append(self.item)
            self.item = None
            self.anchor = None


def parse_directory(html, catalogue):
    parser = DirectoryParser()
    parser.feed(html)
    aliases = {}
    for entry in catalogue.get('brands', []):
        for alias in [entry['name'], *entry.get('aliases', [])]:
            aliases.setdefault(fold(alias), set()).add(entry['id'])
    records = {}
    for row in parser.rows:
        links = [a for a in row['links'] if a['href'] and ''.join(a['text']).strip()]
        if not links:
            continue
        first = links[0]
        name = re.sub(r'\s+', ' ', ''.join(first['text'])).strip()
        name = re.sub(r'\s*\((?:M|HKO|BF)\)\s*', '', name).strip(' -')
        if not name:
            continue
        text = ' '.join(row['text'])
        kind = ('cooperation' if re.search(r'\bHKO\b', text) else
                'operator' if re.search(r'\bBF\b', text) else
                'brand' if re.search(r'\(M\)|\bMarke\b|\bHotelmarke\b', text) else 'unclassified')
        link = urljoin(SOURCE, first['href'])
        if urlsplit(link).scheme not in ('http', 'https'):
            continue
        key = fold(name)
        matches = sorted(aliases.get(key, set()))
        related = sorted({urljoin(SOURCE, a['href']) for a in links[1:]
                          if urlsplit(urljoin(SOURCE, a['href'])).scheme in ('http', 'https')})
        if key in records:
            records[key]['relatedSourceUrls'] = sorted(set(records[key]['relatedSourceUrls'] + related))
            continue
        records[key] = {
            'id': 'hotelier:' + hashlib.sha256(key.encode()).hexdigest()[:16],
            'name': name, 'entityTypeCandidate': kind,
            'sourceUrl': SOURCE, 'profileOrWebsiteUrl': link,
            'websiteCandidate': link if urlsplit(link).hostname not in ('www.hotelier.de', 'hotelier.de') else None,
            'relatedSourceUrls': related,
            'matchedCatalogueIds': matches,
            'reviewStatus': 'existing_name_match' if len(matches) == 1 else 'ambiguous_name' if matches else 'new_candidate',
            'verificationStatus': 'unverified', 'verifiedParentIds': [],
        }
    return sorted(records.values(), key=lambda r: fold(r['name']))


def download(url):
    with urlopen(Request(url, headers={'User-Agent': AGENT}), timeout=30) as response:
        data = response.read(2_000_001)
        if len(data) > 2_000_000:
            raise ValueError('Source exceeded 2 MB limit')
        return data.decode('utf-8')


def safe_cell(value):
    value = str(value)
    return "'" + value if value.lstrip().startswith(('=', '+', '-', '@')) else value


def main():
    args = argparse.ArgumentParser()
    args.add_argument('--html', type=Path, help='Parse a local snapshot without network access')
    args.add_argument('--root', type=Path, default=Path('.'))
    opts = args.parse_args()
    if opts.html:
        html = opts.html.read_text()
    else:
        robots = RobotFileParser()
        robots.parse(download('https://www.hotelier.de/robots.txt').splitlines())
        if not robots.can_fetch(AGENT, SOURCE):
            raise RuntimeError('Source disallows this request in robots.txt')
        html = download(SOURCE)
    catalogue = json.loads((opts.root / 'config/requested-brands.json').read_text())
    records = parse_directory(html, catalogue)
    if len(records) < 100:
        raise RuntimeError(f'Only {len(records)} entries parsed; preserving previous outputs for review')
    stamp = datetime.now(timezone.utc).isoformat()
    summary = {'records': len(records), 'existingNameMatches': sum(r['reviewStatus'] == 'existing_name_match' for r in records),
               'newCandidates': sum(r['reviewStatus'] == 'new_candidate' for r in records),
               'ambiguousNames': sum(r['reviewStatus'] == 'ambiguous_name' for r in records)}
    output = {'schemaVersion': 1, 'source': 'Hotelier.de', 'sourceUrl': SOURCE, 'checkedAt': stamp,
              'sourceSha256': hashlib.sha256(html.encode()).hexdigest(), 'summary': summary,
              'limitations': ['Names and links are discovery candidates, not verified ownership or operating relationships.',
                              'Directory entries may be historical; official company verification is required.',
                              'Exact name matches do not verify entity type, current affiliation or portfolio size.',
                              'No property records or hotel counts are created by this import.'], 'entities': records}
    stream = io.StringIO(newline='')
    writer = csv.writer(stream)
    writer.writerow(['name', 'entity_type_candidate', 'review_status', 'matched_catalogue_ids', 'website_candidate',
                     'profile_or_website_url', 'source_url', 'verification_status', 'checked_at'])
    for r in records:
        writer.writerow([safe_cell(v) for v in [r['name'], r['entityTypeCandidate'], r['reviewStatus'],
                         '|'.join(r['matchedCatalogueIds']), r['websiteCandidate'] or '', r['profileOrWebsiteUrl'],
                         SOURCE, r['verificationStatus'], stamp]])
    targets = {'data/brand-discovery/hotelier.json': json.dumps(output, ensure_ascii=False, indent=2) + '\n',
               'exports/brand-discovery.csv': '\ufeff' + stream.getvalue()}
    for path, content in targets.items():
        target = opts.root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_suffix(target.suffix + '.tmp')
        temporary.write_text(content, encoding='utf-8')
        temporary.replace(target)
    print(json.dumps(summary))


if __name__ == '__main__':
    main()
