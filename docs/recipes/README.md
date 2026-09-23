# Recipes

Step-by-step recipes for common operations.

| Recipe | When to use |
|--------|-------------|
| [add-new-source.md](add-new-source.md) | A new sub-cron started; want its output in the daily rollup |
| [backfill-dedup.md](backfill-dedup.md) | Suspect state pollution; want to clean up `seen_urls.json` |
| [debug-why-article-shipped.md](debug-why-article-shipped.md) | User complains "X article is in today's digest" or "Y is missing" |
| [migrate-state-file.md](migrate-state-file.md) | Upgrading from pre-v0.1 seen_urls.json (legacy raw URL keys) |
| [add-new-tracking-param.md](add-new-tracking-param.md) | New domain emits a new tracker (e.g. `?newclid=...`) |
| [run-end-to-end-test.md](run-end-to-end-test.md) | Verify the rollup works before deploying a code change |

## Quick command reference

```bash
# Run the rollup manually (using production dirs)
python3 -m blog_digest_combined

# Run for a specific date (backfill/test)
python3 -m blog_digest_combined --today 2026-09-22

# Use a non-default output dir
python3 -m blog_digest_combined --output-dir /tmp/rollup-test

# Inspect seen_urls state
python3 -c "
from blog_digest_combined.dedup import load_seen_urls
from pathlib import Path
seen = load_seen_urls(Path.home() / '.hermes/cron/output/combined/seen_urls.json')
for url, date in sorted(seen.items()):
    print(f'{date}  {url}')
"

# Run the test suite
PYTHONPATH=src python3 -m pytest tests/ -v

# Run with coverage
PYTHONPATH=src python3 -m pytest tests/ --cov=blog_digest_combined --cov-fail-under=80
```