# Recipe: Migrate state file

One-shot migration from legacy state format (pre-v0.1) to canonical format.

## When you need this

You upgraded from pre-v0.1 and the rollup starts shipping duplicate
articles. The root cause: state file has raw URL keys, but the lookup
uses canonical keys. Without migration, lookups silently miss.

## Why this matters

The 2026-09-23 incident was exactly this:

1. Pre-v0.1 rollup wrote: `seen_urls["https://example.com/foo/"] = "2026-09-22"`
2. v0.1+ lookup: `canonical_url("https://example.com/foo/") = "https://example.com/foo"`
3. Lookup `"https://example.com/foo" in seen` → **MISS**
4. Article ships again

The fix is two-fold:
1. **Always** canonicalize keys when writing to `seen_urls.json` — done in v0.1
2. **Backfill** the existing state file to use canonical keys — done via
   `migrate_legacy_keys_to_canonical()`

## Run migration

```bash
cd ~/projects/blog-digest-combined
PYTHONPATH=src python3 -c "
from blog_digest_combined.dedup import load_seen_urls, save_seen_urls, migrate_legacy_keys_to_canonical
from pathlib import Path

state_path = Path.home() / '.hermes/cron/output/combined/seen_urls.json'
print(f'State file: {state_path}')

# Backup first
backup = state_path.with_suffix('.json.bak')
state_path.rename(backup)
print(f'Backed up to: {backup}')

# Load → migrate → save
seen = load_seen_urls(backup)  # load from backup
print(f'Before migration: {len(seen)} entries')
migrated = migrate_legacy_keys_to_canonical(seen)
print(f'After migration:  {len(migrated)} entries (collapsed if raw+canonical both present)')
save_seen_urls(state_path, migrated)
print(f'Saved to: {state_path}')
"
```

## Verify migration

```bash
PYTHONPATH=src python3 -c "
from blog_digest_combined.dedup import load_seen_urls, canonical_url
from pathlib import Path

seen = load_seen_urls(Path.home() / '.hermes/cron/output/combined/seen_urls.json')

# All keys should be canonical
non_canonical = [k for k in seen if k != canonical_url(k)]
if non_canonical:
    print(f'WARNING: {len(non_canonical)} non-canonical keys still present')
    for k in non_canonical[:5]: print(f'  {k}')
else:
    print('✅ All keys are canonical')

# No corrupt dates
from datetime import datetime
corrupt = [k for k, v in seen.items() if not _valid_date(v)]
def _valid_date(s):
    try: datetime.strptime(s, '%Y-%m-%d'); return True
    except ValueError: return False

if corrupt:
    print(f'WARNING: {len(corrupt)} corrupt-date entries')
else:
    print('✅ All dates parse')
"
```

## Why the backup-and-load-from-backup pattern?

The `save_seen_urls()` function uses `tmp + rename` — atomic on POSIX
filesystems. But if migration crashes mid-write, you want to know the
file is at the backup path, not corrupted in place.

The pattern:
1. `state_path.rename(backup)` — atomic rename on POSIX. Original file
   is now at `backup`, `state_path` doesn't exist.
2. `load_seen_urls(backup)` — load from backup (migration reads from backup).
3. `save_seen_urls(state_path, migrated)` — atomic write creates new file
   at original path.
4. If anything fails before step 3, the original state is preserved at
   `backup`. Restore with `backup.rename(state_path)`.

## When NOT to migrate

If your state file is already canonical (post-v0.1 deployment), the
migration is a no-op. Check first:

```bash
PYTHONPATH=src python3 -c "
from blog_digest_combined.dedup import load_seen_urls, canonical_url
from pathlib import Path
seen = load_seen_urls(Path.home() / '.hermes/cron/output/combined/seen_urls.json')
raw = [k for k in seen if k != canonical_url(k)]
print(f'Non-canonical keys: {len(raw)}')
"
```

If 0 non-canonical, skip the migration.

## Cleanup: delete the backup after a week

If you've run the rollup for ~7 days post-migration and everything looks
good, delete the backup:

```bash
rm ~/.hermes/cron/output/combined/seen_urls.json.bak
```

Keep the backup around for at least a week in case something goes wrong.