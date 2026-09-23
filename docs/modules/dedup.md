# `dedup` module

> URL canonicalization + cross-day deduplication state.

Source: `src/blog_digest_combined/dedup.py` (213 lines).

## Responsibilities

1. **`canonical_url(u)`** — collapse URL surface variations into a stable key.
2. **`seen_urls.json` I/O** — atomic load/save with corruption recovery.
3. **`is_url_in_recent_days()`** — query-side, including legacy-state recovery.

## Why this module is so heavily tested (30+ cases)

Every sub-cron emits URLs in slightly different shapes (utm params, trailing
slashes, mixed-case host, encoded chars). A naive dedup misses collisions,
and the user sees the same article ship twice. The 2026-09-23 incident was
exactly this bug — `today_kept_urls.add(raw_url)` instead of
`today_kept_urls.add(canonical_url(raw_url))`. Every test in this module
either pins a real edge case (utm_*, fbclid, gclid, etc.) or pins the
regression directly.

## Public API

### `canonical_url(u: str) -> str`

**Contract** (3 invariants, all pinned by tests):
1. **Idempotent**: `canonical_url(canonical_url(x)) == canonical_url(x)`
2. **Pure**: returns input unchanged on any exception (no crash propagation)
3. **Side-effect free**: no I/O, no logging

**What it does** (in order):
1. Strip the fragment (`#...`)
2. Lower-case the host (DNS is case-insensitive)
3. Strip trailing `/` from the path
4. Strip query params matching `_TRACKING_PARAMS` (case-insensitive)
5. Strip query params starting with `_TRACKING_PREFIXES` (just `utm_`)
6. Re-encode the remaining query and return the canonical URL

**What it does NOT do**:
- Sort query params (order is preserved as-is)
- Decode percent-encoding (`%20` and `+` both encode a space; we canonicalize
  the literal `%20` to `+` per URL spec, so they collide correctly)
- Lower-case the path (path is case-sensitive per RFC 3986)
- Drop userinfo (`user:pass@host` — left intact; the user may rely on this)

**Examples**:
```
canonical_url("https://example.com/foo/?utm_source=x&ref=y#bar")
  → 'https://example.com/foo'

canonical_url("https://Example.COM/Path/?fbclid=abc")
  → 'https://example.com/Path'

canonical_url("https://example.com/foo?key=hello%20world")
  → 'https://example.com/foo?key=hello+world'  # + is the query convention
```

**Pinned edge cases** (each has its own test):
| Case | Test | What it pins |
|------|------|--------------|
| Empty string | `test_empty_string` | returns `""`, never raises |
| URL with port | `test_url_with_port` | port preserved (`:443` ≠ no port) |
| Mixed-case host | `test_host_lowercased` | DNS case-insensitive collapse |
| IDN/punycode | `test_idn_punycode` | stays as `xn--` form |
| Multi-value query | `test_repeated_query_keys` | both `?a=1&a=2` values kept |
| Percent encoding | `test_percent_encoded_query_normalized_to_space` | `%20` and `+` collapse |
| Multiple `#` | `test_multiple_fragments_dropped` | all fragments stripped |
| 3rd-party click IDs | `test_tracking_param_aliases_stripped` | fbclid/gclid/mc_cid/_ga/igshid |
| Legitimate params | `test_retain_legitimate_query_params` | `id`, `page`, `keep` preserved |

### `load_seen_urls(path) -> dict[str, str]`

**Contract**: returns `{}` on missing/corrupt file. Never raises.

**Schema**: `{canonical_url: "YYYY-MM-DD"}` — value is the ISO date the URL was
last seen in a rollup output.

**Corruption-recovery matrix** (each pinned):
| File content | Result | Test |
|--------------|--------|------|
| Doesn't exist | `{}` | implicit |
| Valid JSON dict | parsed dict | implicit |
| Empty file | `{}` | `test_empty_file_returns_empty` |
| Only whitespace | `{}` | `test_file_with_only_whitespace` |
| Invalid JSON | `{}` + `[WARN]` | `test_corrupt_json_returns_empty` |
| Top-level list `[1,2,3]` | `{}` + `[WARN]` | `test_json_list_returns_empty` |
| JSON `null` | `{}` + `[WARN]` | `test_json_null_returns_empty` |
| Unicode keys (中文) | UTF-8 in file | `test_save_writes_unicode_escaped` |

### `save_seen_urls(path, data) -> None`

**Contract**: atomic write via `tmp + rename`. Crash mid-write doesn't
corrupt the file.

**Implementation**:
1. Ensure `path.parent.mkdir(parents=True, exist_ok=True)`
2. Write to `path.with_suffix(".tmp")` — same dir, same disk
3. `tmp.replace(path)` — POSIX-atomic on the same filesystem

**Side effects**:
- Sorts keys alphabetically (`sort_keys=True`)
- Pretty-prints (`indent=2`)
- Preserves UTF-8 (`ensure_ascii=False`) — Chinese labels round-trip

### `is_url_in_recent_days(url, seen, today, window_days=3) -> bool`

**Contract**: True iff URL was seen in `[today - window_days, today)`.

Today itself is excluded — caller writes today's URLs AFTER this check runs.

**Two-path lookup**:
- **Fast path**: direct `(url, canonical_url(url)) in seen`
- **Slow path**: legacy `seen` dict keys may be raw URLs — scan all keys,
  re-canonicalize each, find the match. Pinned by
  `TestIsUrlInRecentDaysDualKeyLookup` (5 cases).

**Returns False** when:
- URL is empty/falsy
- `today` isn't a valid ISO date
- Date string in `seen[key]` is corrupt
- Date is outside the window

**Pinned regression** (2026-09-23 bug):
- `test_a_direct_canonical_match` — clean state
- `test_b_raw_form_match_in_seen` — both raw + canonical keys
- `test_c_slow_path_legacy_keys_in_seen` — **the actual 2026-09-23 incident**

### `evict_old_entries(seen, today, window_days=3) -> tuple[dict, int]`

**Contract**: drop entries with `last_seen < today - window_days`.
Returns `(new_state, evicted_count)`.

**Per-test pinned** (`TestEvictOnlyOlderThanWindow`):
- Within window → kept
- Just outside → evicted
- Mixed dates → only old ones evicted

### `migrate_legacy_keys_to_canonical(seen) -> dict[str, str]`

**Contract**: re-key raw-URL entries to canonical form. When multiple entries
collapse to the same canonical key, **keep MAX(date)**.

**Drops** entries with corrupt dates — would otherwise silently bias the window.

**Pinned** (`TestMigrationCollapsesRawAndCanonical`):
- Raw slash + canonical collapse → single entry, MAX wins
- Disjoint keys → preserved
- Idempotent (migrate twice = migrate once)
- Empty input → `{}`
- Corrupt date → dropped

**When to run**:
```bash
# Manual one-shot
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

## Internal constants

```python
_TRACKING_PARAMS = frozenset({
    "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content", "utm_id",
    "ref", "source", "ref_source",
    "fbclid", "gclid", "msclkid", "mc_cid", "mc_eid",
    "igshid", "igclid", "ttclid", "li_fat_id", "li_share",
    "_ga", "_gl", "_hsenc", "_hsmi",
    "from", "refid", "scene",
})
_TRACKING_PREFIXES = ("utm_",)
```

To add a new tracking param, append to `_TRACKING_PARAMS` and add a test case.

## Performance

| Operation | Cost | Bottleneck? |
|-----------|------|-------------|
| `canonical_url` | ~5µs / call | No (stdlib `urlsplit` is fast) |
| `load_seen_urls` (1k entries) | ~5ms | No |
| `save_seen_urls` (1k entries) | ~10ms | No |
| `is_url_in_recent_days` (fast path) | ~10µs | No |
| `is_url_in_recent_days` (slow path, 1k entries) | ~5ms | Yes — slow path scales O(N) |

The slow path is bounded by `seen` size (currently ~50-200 URLs in our production
state). At 1000 URLs, slow-path queries are still <50ms. If `seen` ever grows
past 5000, refactor to a canonical precomputed index.

## Common errors and fixes

### "Same article is shipping twice"

Two possible causes:
1. **`canonical_url` bug** — query URL and seen-key differ in shape. Run the
   `migrate_legacy_keys_to_canonical` recipe.
2. **State file corruption** — `seen_urls.json` is not a dict. Check with:
   ```bash
   cat ~/.hermes/cron/output/combined/seen_urls.json | python3 -c "import sys, json; print(type(json.load(sys.stdin)))"
   ```
   Should print `<class 'dict'>`. If anything else, delete the file and let
   the next run rebuild it.

### "URLs with `?fbclid=...` are not deduplicating"

`fbclid` IS in the tracking-param blocklist. If you're seeing it not get
stripped, the URL might be using a different prefix (`fbclid2`?). Add it to
`_TRACKING_PARAMS` and a corresponding test.