# Brand discovery and verification

Hotelier.de supplies candidate entity names and links, separate from verified brands
and hotel observations. Open [the Excel-compatible review CSV](../exports/brand-discovery.csv)
or [the structured catalogue](../data/brand-discovery/hotelier.json).

The bounded importer requests robots.txt and one directory page. It does not crawl
the whole site, copy article descriptions, collect contacts, or use paid services.
The GitHub workflow publishes this project's catalogue monthly, on relevant code
changes, or manually. It has a five-minute timeout. Network, robots or structural
parse failures fail the run and preserve the previous published files.

Rows contain a stable ID, source link, profile/website link, candidate entity type,
exact name matches against the requested-brand catalogue, and verification status.
Candidate type uses the source's M, HKO, BF or explicit brand markers; otherwise it
remains unclassified. Exact name matches are comparison suggestions only. New
candidates may be alternative names for existing entities, not necessarily new brands.
Related source links are navigation hints, not parent relationships. Names sharing
a profile URL remain distinct: a group profile can describe multiple brands.

All imported entries remain unverified. No hotel count, ownership, parent mapping,
brand matcher alias or production hotel affiliation is changed automatically.
Profile pages have not been crawled; website candidates appear only where the
index directly links outside Hotelier.de. Missing websites and parents stay unknown.

Review an entry against the official company brand portfolio and current company
announcements before promoting it into config/requested-brands.json. Record the
official source URL, date, canonical name, aliases and relationship type. Distinguish
brand ownership, operating companies, franchises and marketing cooperations. Check
historic names and rebrands explicitly. Matching hotel properties is a later step.

Run locally (Python standard library only):

```
python scripts/discover-hotelier-brands.py
python -m unittest discover -s tests -p test_brand_discovery.py -v
```

For offline inspection use `--html path/to/snapshot.html`. A local snapshot is not
republished; the output keeps only factual names, types, links and review metadata.

## Hosting and costs

A public repository is public code/data storage, not a permanently running public
server. Actions supplies temporary runners. Standard public-repository runner
minutes are free; this does not extend to private-repository jobs, paid providers,
larger runners, all storage, databases or external hosting. GitHub execution limits
and acceptable-use terms still apply. This bounded catalogue publication workflow
is separate from a continuously running commercial collection service. Use Render
or another worker platform for that production workload; private code and secrets
must not be published to obtain free compute.

References:
- https://docs.github.com/en/billing/concepts/product-billing/github-actions
- https://docs.github.com/en/actions/reference/limits
- https://docs.github.com/en/site-policy/github-terms/github-terms-for-additional-products-and-features
