# Troubleshooting

Quick reference for diagnosing failures. Each entry has:
- **Symptom** — what you'll see
- **Likely cause** — root cause hypothesis
- **Diagnosis** — command to confirm
- **Fix** — what to do

For step-by-step recovery recipes, see [`recipes/`](recipes/).

---

## Table of contents

1. [Cron fires but no daily digest appears](#case-1-cron-fires-but-no-daily-digest-appears)
2. [Same article ships twice](#case-2-same-article-ships-twice)
3. [Articles missing from today's digest](#case-3-articles-missing-from-todays-digest)
4. [Article body is truncated ("content missing")](#case-4-article-body-is-truncated-content-missing)
5. [Whole section is missing](#case-5-whole-section-is-missing)
6. [State file keeps growing](#case-6-state-file-keeps-growing)
7. [HTML has rendering artifacts](#case-7-html-has-rendering-artifacts)
8. [Wrapper script name collision](#case-8-wrapper-script-name-collision)
9. [CI fails on path test](#case-9-ci-fails-on-path-test)
10. [Sub-cron wrote Pass 3 leniency fallback (N+1 brief)](#case-10-sub-cron-wrote-pass-3-leniency-fallback)

---

## Case 1: Cron fires but no daily digest appears

### Symptom

Cron log shows `combined_feishu.sh` ran, but no file appears in
`~/.hermes/cron/output/combined/` for today.

### Likely cause

All 4 sub-crons failed (empty content) → `main()` returns exit code 2 →
no output written (existing behavior).

### Diagnosis

```bash
ls -la ~/.hermes/cron/output/combined/blog_digest_$(date +%Y-%m-%d).*
# Empty result → confirmed

# Check each sub-cron dir
for job in ae7df3150e0e 909cbd821c57 8836652e22cb hf_papers_watcher; do
    echo "=== $job ==="
    ls ~/.hermes/cron/output/$job/*.md 2>/dev/null | head -3
done
```

### Fix

If sub-cron dirs are all empty, investigate each sub-cron individually.
The rollup is working correctly — it just has nothing to ship.

---

## Case 2: Same article ships twice

### Symptom

User reports "I saw this article in yesterday's digest AND today's digest".

### Likely cause A: canonical URL mismatch (the 2026-09-23 bug)

`seen_urls.json` has raw URLs (with trailing `/` or tracking params), but
the rollup looks up with canonical URLs (no `/`, no tracking params).
Lookup misses → article re-ships.

### Diagnosis

```bash
python3 -c "
from blog_digest_combined.dedup import load_seen_urls, canonical_url
from pathlib import Path
seen = load_seen_urls(Path.home() / '.hermes/cron/output/combined/seen_urls.json')
non_canonical = [k for k in seen if k != canonical_url(k)]
if non_canonical:
    print(f'NON-CANONICAL KEYS ({len(non_canonical)}):')
    for k in non_canonical[:10]: print(f'  {k}')
else:
    print('All keys are canonical')
"
```

If non-canonical keys exist → cause A confirmed.

### Fix

Run the migration (see [`recipes/migrate-state-file.md`](recipes/migrate-state-file.md)):

```bash
PYTHONPATH=~/projects/blog-digest-combined/src python3 -c "
from blog_digest_combined.dedup import load_seen_urls, save_seen_urls, migrate_legacy_keys_to_canonical
from pathlib import Path
p = Path.home() / '.hermes/cron/output/combined/seen_urls.json'
backup = p.with_suffix('.json.bak')
p.rename(backup)
seen = load_seen_urls(backup)
migrated = migrate_legacy_keys_to_canonical(seen)
save_seen_urls(p, migrated)
print(f'Migrated {len(seen)} → {len(migrated)} entries')
"
```

### Likely cause B: sub-cron emits different URL each run

If sub-cron adds a fresh tracking parameter each time, and we haven't
added it to the blocklist, `canonical_url()` returns a different string
per fetch → article re-ships.

### Diagnosis

```bash
python3 -c "
from blog_digest_combined.dedup import canonical_url
# Take two consecutive URLs from the failing sub-cron
url1 = 'https://example.com/article?utm_source=today&new_tracker=abc'
url2 = 'https://example.com/article?utm_source=today&new_tracker=xyz'
c1, c2 = canonical_url(url1), canonical_url(url2)
print(f'Canonical 1: {c1}')
print(f'Canonical 2: {c2}')
print(f'Collide: {c1 == c2}')
"
```

If they don't collide, the new tracker isn't in our blocklist.

### Fix

Add the parameter to `_TRACKING_PARAMS` in
[`src/blog_digest_combined/dedup.py`](modules/dedup.md) — see
[`recipes/add-new-tracking-param.md`](recipes/add-new-tracking-param.md).

---

## Case 3: Articles missing from today's digest

### Symptom A: Specific article X should be in today's digest, but isn't

Most likely cause: dedup'd. The article is in `seen_urls.json` from a
recent shipment (within `DEDUP_WINDOW_DAYS`).

#### Diagnosis

```bash
python3 -c "
from blog_digest_combined.dedup import load_seen_urls, canonical_url
from pathlib import Path
seen = load_seen_urls(Path.home() / '.hermes/cron/output/combined/seen_urls.json')
url = input('URL to check: ').strip()
canonical = canonical_url(url)
print(f'Looking for: {canonical}')
print(f'In state: {canonical in seen}')
"
```

#### Fix

If legitimately should ship today, remove from state — see
[`recipes/backfill-dedup.md`](recipes/backfill-dedup.md).

### Symptom B: Whole section from one source missing

#### Diagnosis

```bash
# Check the sub-cron brief has the section
head -20 ~/.hermes/cron/output/<job_id>/brief.md

# Run the parser manually
python3 -c "
from blog_digest_combined.parser import parse_sections
from blog_digest_combined.extractor import extract_clean_content
from blog_digest_combined.fetcher import load_job_content
from pathlib import Path

content, _ = load_job_content(Path.home() / '.hermes/cron/output/<job_id>', today='2026-09-23')
sections, stats = parse_sections(content, today='2026-09-23', recent_seen={}, cross_job_seen=set())
print(f'Sections: {len(sections)}')
for sec in sections:
    print(f'  ## {sec[\"title\"]}: {len(sec[\"articles\"])} articles')
print(f'Stats: {stats}')
"
```

#### Fix

If sub-cron brief has `## heading` but parser produces 0 sections, the
brief format diverged from expected. Update either:
- Sub-cron prompt to produce `## heading` sections
- OR `parser.py` to handle the new format

---

## Case 4: Article body is truncated ("content missing")

### Symptom

User reports "this section looks short" or "the article has no body".

### Likely cause A: N+1 brief leaked (the 2026-09-23 bug)

Sub-cron ran late into tomorrow's mtime window. Rollup picked tomorrow's
brief. Today's digest ships with truncated (tomorrow's) content.

#### Diagnosis

```bash
# Check the rollup logs
python3 -m blog_digest_combined --today 2026-09-23 2>&1 | grep "back-day fallback"
# Or:
python3 -m blog_digest_combined --today 2026-09-23 2>&1 | grep "INFO.*get_latest_md"

# Check the job's brief files
ls -la ~/.hermes/cron/output/ae7df3150e0e/
# Look for files dated 2026-09-24 (N+1 leak)
```

If you see a 2026-09-24 brief in a 2026-09-23 dir → cause A confirmed.

#### Fix

1. The `fetcher.get_latest_md` Pass 1 enforces today-bound selection, so
   Pass 1 should have rejected N+1.
2. If you see `[INFO] get_latest_md(...): back-day fallback to 2026-09-22`
   in the logs, the today brief is missing AND only N-1 is available. That's
   expected (sub-cron ran late). Investigate why today brief wasn't written.
3. If the Pass 3 fallback fires (no today header in any brief), there's a
   deeper issue with the sub-cron format. See
   [`modules/fetcher.md`](modules/fetcher.md#operator-warning-for-pass-3-leakage).

### Likely cause B: `## Response` not found in brief

The extractor returns early — only content from after `## Response`.

#### Diagnosis

```bash
head -50 ~/.hermes/cron/output/<job_id>/brief.md | grep "## Response"
# Should print the line with the marker
```

If no `## Response`, the sub-cron didn't follow the protocol.

#### Fix

Update sub-cron prompt to include `## Response` marker. Or patch
`extractor.py` to handle the alternative marker — add a regression test.

---

## Case 5: Whole section is missing

Same diagnosis as Case 3 Symptom B — see above.

---

## Case 6: State file keeps growing

### Symptom

`seen_urls.json` size exceeds expected bounds. Currently ~10KB for 95 URLs.
If you see >50KB, something's off.

### Likely cause

`evict_old_entries` isn't being called, or the window isn't doing what
you think.

### Diagnosis

```bash
python3 -c "
from blog_digest_combined.dedup import load_seen_urls, evict_old_entries
from datetime import date
from pathlib import Path
seen = load_seen_urls(Path.home() / '.hermes/cron/output/combined/seen_urls.json')
print(f'Total entries: {len(seen)}')
new, evicted = evict_old_entries(seen, date.today().strftime('%Y-%m-%d'), window_days=3)
print(f'Evicted: {evicted}')
print(f'Remaining after eviction: {len(new)}')
"
```

If `evicted == 0` but the file is huge, your entries all have recent dates
(or dates are corrupt — `evict_old` keeps them).

### Fix

If dates are corrupt:
```bash
python3 -c "
from blog_digest_combined.dedup import load_seen_urls, save_seen_urls
from pathlib import Path
p = Path.home() / '.hermes/cron/output/combined/seen_urls.json'
seen = load_seen_urls(p)
# Filter to valid dates
from datetime import datetime
clean = {u: d for u, d in seen.items() if _is_valid(d)}
def _is_valid(s):
    try: datetime.strptime(s, '%Y-%m-%d'); return True
    except ValueError: return False
print(f'Clean: {len(clean)} / Original: {len(seen)}')
save_seen_urls(p, clean)
"
```

If dates are all valid but eviction isn't reducing → your `window_days=3`
window is being outpaced by the new URL rate. Either:
- Bump `DEDUP_WINDOW_DAYS` to a shorter value
- Or there's a bug — report at https://github.com/YiJing233/blog-digest-combined/issues

---

## Case 7: HTML has rendering artifacts

### Symptom

HTML output has stray `<script>`, `<img onerror>`, weird quotes, etc.

### Likely cause

Either:
1. Body content wasn't escaped (regression in renderer)
2. URL contains HTML-escape chars (e.g. `&`, `"`, `<`)
3. CSS styling is being overridden

### Diagnosis

```bash
# Look at the actual HTML
head -200 ~/.hermes/cron/output/combined/blog_digest_2026-09-23.html | grep -i "<script"
# Should NOT find anything inside the body

# Check the body's HTML escape
python3 -c "
from blog_digest_combined.renderer import render_html
from blog_digest_combined.parser import parse_sections
from blog_digest_combined.extractor import extract_clean_content
from blog_digest_combined.fetcher import load_job_content
from pathlib import Path

content, _ = load_job_content(Path.home() / '.hermes/cron/output/ae7df3150e0e', today='2026-09-23')
sections, _ = parse_sections(content, today='2026-09-23', recent_seen={}, cross_job_seen=set())
sources_data = [{'label': 'X', 'sections': sections, 'job_id': 'x'}]
html = render_html(sources_data, '2026-09-23')
import re
bad = re.findall(r'<script[^>]*>', html)
if bad: print(f'FOUND <script>: {bad}')
else: print('No <script> tags')
"
```

### Fix

If `<script>` tags found, the renderer is regressed. The fix is in
[`src/blog_digest_combined/renderer.py:render_article()`](modules/renderer.md#xss-defense).
Add the regression test that should have caught this:

```python
def test_no_inner_script_after_xss_in_title_and_body(self):
    sources = [{"label": "X", "sections": [{
        "title": "S", "articles": [
            {"title": "<script>alert(1)</script>",
             "url": "javascript:alert(2)",
             "body": "<img src=x onerror=alert(3)>"},
        ],
    }]}]
    html = render_html(sources, "2026-09-23")
    assert "<script>alert(1)" not in html
    assert "javascript:" not in html or "&lt;script&gt;" in html
```

---

## Case 8: Wrapper script name collision

### Symptom

```
ModuleNotFoundError: No module named 'blog_digest_combined.cli';
'blog_digest_combined' is not a package
```

### Likely cause

The thin wrapper is at `~/.hermes/scripts/blog_digest_combined.py` —
when Python sees `blog_digest_combined.py` in `cwd` or sys.path, it
prefers the file over the installed package of the same name.

### Diagnosis

```bash
ls -la ~/.hermes/scripts/blog_digest_combined*.py
```

If `blog_digest_combined.py` exists (not `_wrapper.py`), this is the
collision.

### Fix

Rename the wrapper (the canonical recipe):

```bash
mv ~/.hermes/scripts/blog_digest_combined.py \
   ~/.hermes/scripts/blog_digest_combined_wrapper.py

# Update combined_feishu.sh
sed -i 's/python3 blog_digest_combined.py$/python3 blog_digest_combined_wrapper.py/' \
    ~/.hermes/scripts/combined_feishu.sh
```

(See [`CHANGELOG.md`](../CHANGELOG.md) entry for v0.1.0 migration.)

---

## Case 9: CI fails on path test

### Symptom

```
AssertionError: assert PosixPath('/home/runner/.hermes/cron/output/...') == 
PosixPath('/home/yiking/.hermes/cron/output/...')
```

### Likely cause

A test hardcoded a path like `/home/yiking/...` — only works on the dev
machine, fails in CI.

### Fix

Use `Path.home()` or assert structural properties only:

```python
# WRONG
assert cli.JOB_DIR_OVERRIDES["hf_papers_watcher"] == Path("/home/yiking/.hermes/cron/output/hf_papers_watcher")

# RIGHT
p = cli.JOB_DIR_OVERRIDES["hf_papers_watcher"]
assert p.name == "hf_papers_watcher"
assert p.parent.name == "output"
```

---

## Case 10: Sub-cron wrote Pass 3 leniency fallback (N+1)

### Symptom

`[INFO] get_latest_md(<job>): today=... → back-day fallback to <date>`

In a log line, OR a `[WARN]` if Pass 3 fired with N+1.

### Likely cause

Sub-cron wrote a tomorrow-dated brief into today's directory (clock
drift, retry-with-tomorrow's-date, or sub-cron's date math is off).

### Diagnosis

```bash
# Look at file dates and content headers
for f in ~/.hermes/cron/output/<job_id>/*.md; do
    echo "=== $f ==="
    head -1 "$f"
    stat -c '%y' "$f" | head -c 16
    echo
done
```

### Fix

1. Sub-cron side: investigate why a N+1 brief was written. Re-run
   sub-cron with `--today $(date +%Y-%m-%d)` to overwrite stale N+1.
2. Rollup side: if Pass 3 lenient mode is causing problems, document
   the constraint and bump the sub-cron to be deterministic. The Pass 3
   leak is documented as a known-limitation; the fix is upstream.

---

## Reporting new bugs

After exhausting the recipes above:

1. Check existing GitHub issues: https://github.com/YiJing233/blog-digest-combined/issues
2. File a new issue with:
   - Symptom (user-visible behavior)
   - Reproduction (cron logs + state file content)
   - Diagnosis output (commands you tried)
   - Expected vs actual behavior
3. Add a regression test to `tests/test_*.py` that fails on the bug
4. PR with the fix + the regression test

The 170-test suite exists exactly to pin these regressions. Help us keep it tight.