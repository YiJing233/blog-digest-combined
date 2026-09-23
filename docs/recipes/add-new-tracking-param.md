# Recipe: Add a new tracking param to `canonical_url()`

When a new domain emits a new tracking parameter (e.g. `?newclid=...`) and
you don't want it polluting `seen_urls.json`.

## When to do this

- A new sub-cron domain starts appending click IDs that vary across
  requests (so `canonical_url` returns a different string per fetch)
- You see the same article ship twice because the URL differs by a tracker
- A new platform introduces a new convention (e.g. Twitter `?t=...`)

## Steps

### 1. Identify the parameter

Run the failing case through the canonical URL:

```bash
python3 -c "
from blog_digest_combined.dedup import canonical_url
a = canonical_url('https://example.com/foo?newclid=abc')
b = canonical_url('https://example.com/foo?newclid=xyz')
print(f'a: {a}')
print(f'b: {b}')
print(f'Collide: {a == b}')
"
```

If `a != b`, the parameter is NOT being stripped. Time to add it.

### 2. Add to `_TRACKING_PARAMS`

Edit `src/blog_digest_combined/dedup.py`:

```python
_TRACKING_PARAMS = frozenset({
    # ... existing params ...
    "newclid",       # ← NEW (lowercase)
})
```

If the parameter has a prefix pattern (like `utm_*`), also add to
`_TRACKING_PREFIXES`:

```python
_TRACKING_PREFIXES = ("utm_", "newprefix_")   # ← NEW
```

### 3. Add a test

Edit `tests/test_dedup.py`:

```python
class TestCanonicalUrlEdgeCases:
    def test_tracking_param_aliases_stripped(self):
        cases = [
            # ... existing cases ...
            ("https://example.com/foo?newclid=abc",
             "https://example.com/foo"),     # ← NEW
        ]
        for raw, expected in cases:
            got = canonical_url(raw)
            assert got == expected, f"failed: {raw!r} → {got!r} (want {expected!r})"
```

### 4. Verify

```bash
PYTHONPATH=src python3 -c "
from blog_digest_combined.dedup import canonical_url
a = canonical_url('https://example.com/foo?newclid=abc')
b = canonical_url('https://example.com/foo?newclid=xyz')
assert a == b, f'{a!r} != {b!r}'
print(f'✅ newclid tracked: {a}')
"

# Run the full test suite
PYTHONPATH=src python3 -m pytest tests/test_dedup.py -v
```

### 5. Deploy

```bash
pip install -e ~/projects/blog-digest-combined --upgrade
```

Cron will pick up the new canonical rules on next run.

## Naming conventions

- Match the parameter name as the platform uses it (lowercase)
- If multiple variants exist (`fbclid`, `igclid`, `ttclid`), prefer the
  most general category

Examples from production:
- `gclid` — Google Click Identifier (any Google Ads source)
- `fbclid` — Facebook Click Identifier
- `mc_cid` / `mc_eid` — Mailchimp campaign / email IDs
- `li_fat_id` / `li_share` — LinkedIn share tracking
- `_ga` / `_gl` — Google Analytics

## Common false positives

Don't strip parameters that look like trackers but aren't:

- `id` (article ID, content ID)
- `page`, `p`, `n` (pagination)
- `lang`, `locale` (internationalization)
- `v`, `version` (resource versioning)
- `ref` (sometimes legit, e.g. `?ref=homepage`)

The `_TRACKING_PARAMS` set is for **click attribution IDs** specifically.
If unsure, check if the parameter changes per request (true trackers do)
or per content (real IDs don't).

## When not to add to the blocklist

If a parameter is a content identifier (like `?id=42`), removing it would
merge genuinely-different articles. Better to keep it canonical.

If the parameter is encoded with semantic meaning (like `?q=hello+world`),
stripping it changes the article identity.