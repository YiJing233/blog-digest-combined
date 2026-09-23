# Recipe: Debug "why did article X ship (or not ship)"

When user complains about specific article inclusion/exclusion in a digest.

## Use case 1: User reports "article X is in today's digest but shouldn't be"

### Step 1: Find the URL in `seen_urls.json`

```bash
python3 -c "
from blog_digest_combined.dedup import load_seen_urls, canonical_url
from pathlib import Path
seen = load_seen_urls(Path.home() / '.hermes/cron/output/combined/seen_urls.json')
url = input('URL: ').strip()
canonical = canonical_url(url)
print(f'Looking for: {canonical}')
print(f'Match in state: {canonical in seen}')
print(f'Date in state:  {seen.get(canonical, \"N/A\")}')
"
```

If the URL is in `seen_urls.json`, it WAS shipped before. Dedup shouldn't
re-ship it. So either:
- The state file got out of sync with reality
- The article legitimately re-appeared in a new feed

### Step 2: Check the source brief

What source produced it?

```bash
grep -l "<URL>" ~/.hermes/cron/output/*/brief*.md
```

Look at the source brief — does the article still appear there? If yes,
the rollup's `is_url_in_recent_days` should have dedup'd it. Check
the canonical URL form matches the state file key.

### Step 3: Run with debug logging

Re-run the rollup with verbose logging:

```bash
python3 -c "
import logging
logging.basicConfig(level=logging.DEBUG)
from blog_digest_combined.cli import build_sources_data
sources, failed, empty, urls = build_sources_data('2026-09-23')
print(f'Failed jobs: {failed}')
print(f'Empty jobs: {empty}')
print(f'Today canonical URLs ({len(urls)}):')
for u in sorted(urls): print(f'  {u}')
"
```

If the URL appears in the output, it's being kept today.

## Use case 2: User reports "article X should be in today's digest but isn't"

### Step 1: Check if the URL is in `seen_urls.json`

If yes, dedup is working as intended (recently shipped). Decide:
- Bump `DEDUP_WINDOW_DAYS` to extend the dedup window? → not recommended
- Remove the entry from state? → see recipe `backfill-dedup.md`

### Step 2: Check the source brief

```bash
grep -l "search-term-from-article" ~/.hermes/cron/output/*/brief*.md
```

If the article is in a source brief, parse_sections should have picked it
up. Run the parser manually:

```bash
python3 -c "
from pathlib import Path
from blog_digest_combined.extractor import extract_clean_content
from blog_digest_combined.fetcher import load_job_content
from blog_digest_combined.parser import parse_sections

content, mtime = load_job_content(Path.home() / '.hermes/cron/output/ae7df3150e0e', today='2026-09-23')
print(f'Content length: {len(content)} chars')
sections, stats = parse_sections(content, today='2026-09-23', recent_seen={}, cross_job_seen=set())
print(f'Sections: {len(sections)}')
print(f'Stats: {stats}')
for sec in sections:
    print(f'  ## {sec[\"title\"]} — {len(sec[\"articles\"])} articles')
    for art in sec['articles']:
        print(f'    [{art[\"num\"]}] {art[\"title\"]} — {art[\"url\"]}')
"
```

This shows you exactly what the parser kept and what got dropped.

### Step 3: Check the article body

If the article IS in the parser output, but not in the final HTML, the
problem is in `renderer`. Check the renderer directly:

```bash
python3 -c "
from blog_digest_combined.renderer import render_html
from blog_digest_combined.parser import parse_sections
from blog_digest_combined.extractor import extract_clean_content
from blog_digest_combined.fetcher import load_job_content
from pathlib import Path

content, mtime = load_job_content(Path.home() / '.hermes/cron/output/ae7df3150e0e', today='2026-09-23')
sections, _ = parse_sections(content, today='2026-09-23', recent_seen={}, cross_job_seen=set())
sources_data = [{'label': 'iCloud', 'sections': sections, 'job_id': 'ae7df3150e0e'}]
html = render_html(sources_data, '2026-09-23')
# Search for the article title
import sys
title = sys.argv[1] if len(sys.argv) > 1 else input('Title: ')
print('Title in HTML:', title in html)
" "<title>"
```

## Use case 3: A whole section is missing

### Check section heading pattern

The parser splits on `## <title>`. If your sub-cron uses `### ` (one
level deeper), or doesn't use markdown headers at all, the sections won't
appear.

Verify:

```bash
head -20 ~/.hermes/cron/output/<job_id>/brief.md
```

Should look like:

```
**日期**：2026-09-23

## Some Section Name

**[1] Article Title**
...
```

If `##` is missing, the parser will silently produce zero sections.

## Common root causes

| Symptom | Root cause | Fix |
|---------|------------|-----|
| All articles from one source missing | sub-cron failed or empty | check sub-cron logs |
| One specific article missing | dedup'd (in seen_urls.json) | remove from state or wait |
| Article body is truncated | `## Response` not detected | check extractor against the brief |
| Whole sections missing | `## heading` not present | update sub-cron prompt |
| Articles without URLs dropped | body has no `https://...` | update sub-cron prompt |
| HTML has weird artifacts | body contains `</p>` or HTML | check body XSS escape in renderer |

## Adding logging to the rollup

If you need to trace every URL through the pipeline, add to `cli.main()`:

```python
import logging
logging.basicConfig(level=logging.DEBUG)
```

Or just run the rollup with `--output-dir` to a temp dir and grep
through the output. The print statements in the rollup already log:
- `[INFO] <label> (<job_id>): N chars clean, mtime=...`
- `[DEDUP] <label>: dropped N cross-day duplicate(s)`
- `[DEDUP] <label>: dropped N cross-job duplicate(s)`
- `[INFO]   → N sections, M articles`

Read these for the full trace.