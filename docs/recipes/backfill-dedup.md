# Recipe: Backfill and clean `seen_urls.json`

When `seen_urls.json` has stale entries, corrupt data, or unwanted dedup hits.

## When to do this

- An article was supposed to ship but got dedup'd — maybe the canonical key
  is wrong for that URL
- The state file has garbage entries from a botched migration
- You changed `DEDUP_WINDOW_DAYS` and want to drop old entries

## Quick commands

### View current state

```bash
python3 -c "
from blog_digest_combined.dedup import load_seen_urls
from pathlib import Path
seen = load_seen_urls(Path.home() / '.hermes/cron/output/combined/seen_urls.json')
print(f'Total entries: {len(seen)}')
for url, date in sorted(seen.items(), key=lambda x: x[1]):
    print(f'{date}  {url}')
"
```

### Drop entries older than N days

```bash
python3 -c "
from blog_digest_combined.dedup import load_seen_urls, save_seen_urls, evict_old_entries
from datetime import date
from pathlib import Path
p = Path.home() / '.hermes/cron/output/combined/seen_urls.json'
seen = load_seen_urls(p)
new, n = evict_old_entries(seen, date.today().strftime('%Y-%m-%d'), window_days=3)
print(f'Evicted {n} entries (older than 3 days)')
save_seen_urls(p, new)
"
```

### Migrate legacy raw-URL keys to canonical

(One-time, after upgrading from pre-v0.1.)

```bash
python3 -c "
from blog_digest_combined.dedup import load_seen_urls, save_seen_urls, migrate_legacy_keys_to_canonical
from pathlib import Path
p = Path.home() / '.hermes/cron/output/combined/seen_urls.json'
seen = load_seen_urls(p)
print(f'Before: {len(seen)} entries')
seen = migrate_legacy_keys_to_canonical(seen)
print(f'After:  {len(seen)} entries')
save_seen_urls(p, seen)
"
```

### Remove a specific URL

```bash
python3 -c "
from blog_digest_combined.dedup import load_seen_urls, save_seen_urls, canonical_url
from pathlib import Path
p = Path.home() / '.hermes/cron/output/combined/seen_urls.json'
seen = load_seen_urls(p)
url = canonical_url(input('URL to remove: ').strip())
if url in seen:
    del seen[url]
    save_seen_urls(p, seen)
    print(f'Removed: {url}')
else:
    print(f'Not found: {url}')
"
```

### Reset state entirely (start fresh)

⚠️ **WARNING**: this will re-send every article from the last 3+ days.

```bash
python3 -c "
from pathlib import Path
p = Path.home() / '.hermes/cron/output/combined/seen_urls.json'
if p.exists():
    p.unlink()
    print(f'Removed: {p}')
print('Next rollup will rebuild state from scratch')
"
```

## Detailed migration: pre-v0.1 → v0.1+

The legacy state format (pre-v0.1) had **raw URL keys** (with trailing `/`,
without `canonical_url()` applied):

```json
{
  "https://example.com/foo/": "2026-09-22",
  "https://example.com/bar?utm_source=x": "2026-09-22"
}
```

The v0.1+ format has **canonical keys** (no trailing `/`, no tracking params):

```json
{
  "https://example.com/foo": "2026-09-22",
  "https://example.com/bar": "2026-09-22"
}
```

Without migration, an old raw-URL entry would NOT match a new canonical
lookup. The result: same article ships twice (the 2026-09-23 bug).

The `migrate_legacy_keys_to_canonical()` function handles this safely:
- Re-canonicalizes each key
- Keeps MAX(date) when multiple entries collapse to the same canonical key
- Drops entries with corrupt dates

`is_url_in_recent_days()` ALSO has a slow-path fallback that does this
lookup on-the-fly. So even without migrating, the rollup doesn't break.
But the migration cleans up the state file and removes the slow-path cost.

## Verify migration worked

After running migration, check that no obvious raw keys remain:

```bash
python3 -c "
from blog_digest_combined.dedup import load_seen_urls, canonical_url
from pathlib import Path
seen = load_seen_urls(Path.home() / '.hermes/cron/output/combined/seen_urls.json')
raw = [k for k in seen if k != canonical_url(k)]
if raw:
    print(f'{len(raw)} non-canonical keys still present:')
    for k in raw[:10]: print(f'  {k}')
else:
    print('All keys are canonical.')
"
```

## What NOT to do

### Don't edit `seen_urls.json` by hand

Reason: JSON must be valid, sorted by key, UTF-8, ensure_ascii=False. A
typo breaks the next cron run.

If you need to remove a single URL, use the Python snippet above.

### Don't bump `DEDUP_WINDOW_DAYS=0` to skip dedup

Reason: same article will ship every day. Operator annoyance compounds.

If you genuinely want no dedup, run `main()` once with the option to
write to a fresh state file. Then never look at state.

### Don't share `seen_urls.json` across cron hosts

Reason: canonical keys are universal, but cron clocks differ. Two hosts
could write different dates for the same URL → state corruption.

If you need cross-host dedup, use an external store (Redis, etc). For now
this is single-host only.