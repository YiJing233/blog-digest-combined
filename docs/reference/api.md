# Python API Reference

The package is `blog_digest_combined`. Five modules + the CLI entry point.

## Top-level imports

```python
from blog_digest_combined.dedup import (
    canonical_url,
    load_seen_urls,
    save_seen_urls,
    is_url_in_recent_days,
    evict_old_entries,
    migrate_legacy_keys_to_canonical,
)
from blog_digest_combined.extractor import extract_clean_content
from blog_digest_combined.fetcher import get_latest_md, load_job_content
from blog_digest_combined.parser import parse_sections, clean_body
from blog_digest_combined.renderer import render_html, render_markdown, render_article
from blog_digest_combined import cli
```

## Quick start

### Run the rollup

```python
from blog_digest_combined.cli import main
import sys

# Default: today's date, ~/.hermes/cron/output/
exit_code = main([])

# Backfill/test
exit_code = main(["--today", "2026-09-22"])

# Use a non-default output dir
exit_code = main(["--output-dir", "/tmp/rollup-test"])
```

Exit codes: `0` success, `2` no content.

### Render a single article

```python
from blog_digest_combined.renderer import render_article
art = {
    "title": "中文标题",
    "url":   "https://example.com/foo",
    "body":  "背景：...\n\n核心观点：...",
}
html = render_article(art)
```

### Build a full digest programmatically

```python
from blog_digest_combined.cli import build_sources_data
from blog_digest_combined.renderer import render_html

sources_data, failed, empty, today_urls = build_sources_data("2026-09-23")
print(f"Failed jobs: {failed}")
print(f"Empty jobs: {empty}")
print(f"Shipping {len(today_urls)} URLs")

html = render_html(sources_data, "2026-09-23")
# Save manually
with open("/tmp/digest.html", "w") as f:
    f.write(html)
```

---

## `dedup` module

### `canonical_url(u: str) -> str`

Canonicalize URL: strip tracking params + fragment + trailing slash;
lowercase the host.

```python
>>> canonical_url("https://example.com/foo/?utm_source=x&ref=y#bar")
'https://example.com/foo'
>>> canonical_url("Example.COM/Foo/?fbclid=123")
'https://example.com/Foo'
```

Returns input unchanged on any exception (never raises).

[Full contract & edge cases →](../modules/dedup.md#canonical_urlu-str---str)

### `load_seen_urls(path) -> dict[str, str]`

Load `seen_urls.json`. Schema: `{canonical_url: "YYYY-MM-DD"}`.

```python
from pathlib import Path
seen = load_seen_urls(Path.home() / ".hermes/cron/output/combined/seen_urls.json")
```

Returns `{}` on missing/corrupt file. Never raises.

### `save_seen_urls(path, data) -> None`

Atomic write (tmp + rename). JSON output:
- Sorted keys
- UTF-8 (Chinese labels preserved)
- Pretty-printed (indent=2)

```python
data = {
    "https://example.com/foo": "2026-09-22",
    "https://example.com/baz": "2026-09-23",
}
save_seen_urls("/tmp/state.json", data)
```

### `is_url_in_recent_days(url, seen, today, window_days=3) -> bool`

True iff URL was seen in `[today - window_days, today)`.

Two-path lookup:
- Fast path: direct canonical hit in `seen`
- Slow path: legacy-state recovery — scan all keys, re-canonicalize, look for match

Today itself is excluded (chicken-and-egg safety).

```python
if is_url_in_recent_days("https://example.com/foo", seen, "2026-09-23"):
    print("Already shipped today-1 or today-2, dedup")
```

### `evict_old_entries(seen, today, window_days=3) -> tuple[dict, int]`

Drop entries older than `today - window_days`. Returns `(new_state, evicted_count)`.

```python
new, n = evict_old_entries(seen, "2026-09-23", window_days=3)
print(f"Evicted {n} entries")
```

### `migrate_legacy_keys_to_canonical(seen) -> dict[str, str]`

Re-key raw-URL entries to canonical form. When multiple entries collapse,
keeps MAX(date). Drops entries with corrupt dates.

```python
migrated = migrate_legacy_keys_to_canonical(seen)
save_seen_urls(path, migrated)
```

See [`recipes/migrate-state-file.md`](../recipes/migrate-state-file.md) for the full migration recipe.

---

## `extractor` module

### `extract_clean_content(raw_content: str) -> str`

Strip `## Prompt` block + truncate trailing notes. Returns clean content.

```python
raw = """# Cron Job: X
## Prompt
... (50KB SKILL.md dump) ...
## Response
**日期**：2026-09-23
... actual content ...
"""

content = extract_clean_content(raw)
# content is just the part after `## Response`, with trailing `---` stripped
```

Edge cases:
- Empty input → `""`
- `(FAILED)` on first line → `""` (whole-job failure)
- Only `## Prompt` (no `## Response`) → returns everything after `## Prompt`

---

## `fetcher` module

### `get_latest_md(job_dir, today=None, allow_back_days=2) -> tuple[Optional[str], Optional[str]]`

Select the right brief for today's rollup. 4-pass ladder (today / N-1/N-2 / any-header / mtime-fallback).

```python
from pathlib import Path
path, mtime = get_latest_md(
    Path.home() / ".hermes/cron/output/ae7df3150e0e",
    today="2026-09-23",
)
if path:
    print(f"Selected: {path} (mtime={mtime})")
```

Pass 1 + 2 enforce today-bound selection — N+1 brief never picked when today exists.

[Full pass ladder →](../modules/fetcher.md#get_latest_mdjob_dir-todayNone-allow_back_days_2)

### `load_job_content(job_dir, today=None) -> tuple[str, str]`

Convenience wrapper: `get_latest_md` + `extract_clean_content`.

```python
content, mtime = load_job_content(
    Path.home() / ".hermes/cron/output/ae7df3150e0e",
    today="2026-09-23",
)
if not content:
    print("Job failed (no usable content)")
```

---

## `parser` module

### `parse_sections(text, today, recent_seen=None, cross_job_seen=None, window_days=3) -> tuple[list[dict], dict]`

Parse markdown into sections. Apply two-level URL dedup.

```python
sections, stats = parse_sections(
    content,
    today="2026-09-23",
    recent_seen=load_seen_urls(state_path),
    cross_job_seen=set(),
    window_days=3,
)

for sec in sections:
    print(f"## {sec['title']}")
    for art in sec["articles"]:
        print(f"  [{art['num']}] {art['title']}")
        print(f"      URL: {art['url']}")
        print(f"      Body: {art['body'][:80]}...")

print(f"Stats: {stats}")
# {'cross_day_drops': 5, 'cross_job_drops': 2, 'kept': 18}
```

**Important**: `cross_job_seen` is **mutated in-place** — pass the same set across multiple `parse_sections` calls (one per sub-cron). This is the only way cross-job dedup works.

[Full contract →](../modules/parser.md#parse_sectionstext-today-recent_seenNone-cross_job_seenNone-window_days_3)

### `clean_body(raw: str) -> str`

Strip residual markdown inline syntax; preserve paragraph breaks.

```python
out = clean_body("**bold** and *em* and `code` and [link](url)")
# '<strong>bold</strong> and <em>em</em> and <code>code</code> and link'
```

---

## `renderer` module

### `render_html(sources_data, today_str) -> str`

Render to Kami-themed HTML.

```python
from blog_digest_combined.renderer import render_html

sources_data = [
    {
        "label": "iCloud 订阅",
        "sections": [
            {
                "title": "🔬 技术深度",
                "articles": [
                    {"title": "Foo", "url": "https://example.com", "body": "..."},
                ],
            },
        ],
    },
]
html = render_html(sources_data, "2026-09-23")
# Returns full HTML document with embedded CSS
```

Output includes:
- `<!DOCTYPE html>` + `<html lang="zh-CN">`
- Kami CSS theme (Inter, Newsreader, Noto Serif SC)
- Article cards with `.article-inner`, `.article-accent`
- Source badges (only active sources)
- Footer with date

### `render_markdown(sources_data, today_str) -> str`

Render to Markdown. Same input shape as `render_html`.

```python
from blog_digest_combined.renderer import render_markdown

md = render_markdown(sources_data, "2026-09-23")
print(md)
# # 日报汇总 | 2026-09-23
# 
# 共筛选自 1 个来源 · 1 篇精选
# 
# ## iCloud 订阅
# 
# ### [Foo](https://example.com)
# 
# ...
```

### `render_article(art) -> str`

Render a single article to HTML. Escapes title and URL.

```python
art = {
    "title": "中文标题",
    "url":   "https://example.com/foo",
    "body":  "背景：...\n\n核心观点：...",
}
html = render_article(art)
```

---

## `cli` module

### `main(argv=None) -> int`

The cron entry point. Wires all modules together.

```python
from blog_digest_combined.cli import main

# Default: today, ~/.hermes/cron/output/
exit_code = main([])

# Backfill
exit_code = main(["--today", "2026-09-22"])

# Custom output dir
exit_code = main(["--output-dir", "/tmp/rollup-test"])
```

Exit codes:
- `0`: success
- `2`: no articles kept (all failed or all dedup'd)

### `build_sources_data(today) -> tuple[list[dict], list[str], list[str], set[str]]`

Walk all configured jobs. Run `parse_sections` per job. Returns the
structured data for `render_*` calls.

```python
sources_data, failed_jobs, empty_jobs, today_urls = build_sources_data("2026-09-23")
print(f"Failed: {failed_jobs}")
print(f"Empty after dedup: {empty_jobs}")
print(f"Shipping {len(today_urls)} canonical URLs")
```

### Constants

```python
from blog_digest_combined import cli

JOBS = cli.JOBS
# {"iCloud 订阅": "ae7df3150e0e", ...}

JOB_DIR_OVERRIDES = cli.JOB_DIR_OVERRIDES
# {"hf_papers_watcher": Path(...), ...}

DEFAULT_OUTPUT_BASE = cli.DEFAULT_OUTPUT_BASE
# Path.home() / ".hermes" / "cron" / "output"

DEDUP_WINDOW_DAYS = cli.DEDUP_WINDOW_DAYS
# int, default 3
```

---

## Calling order (what to do when)

For programmatic use, the typical order is:

```python
# 1. Aggregate data
sources_data, failed, empty, urls = build_sources_data("2026-09-23")

# 2. Render
html = render_html(sources_data, "2026-09-23")
md   = render_markdown(sources_data, "2026-09-23")

# 3. Write
with open("digest.html", "w") as f: f.write(html)
with open("digest.md",   "w") as f: f.write(md)

# 4. Update state
from blog_digest_combined.dedup import load_seen_urls, save_seen_urls
state_path = Path.home() / ".hermes/cron/output/combined/seen_urls.json"
seen = load_seen_urls(state_path)
seen.update({u: "2026-09-23" for u in urls})
save_seen_urls(state_path, seen)
```

Or just call `main()` and let it do all of this for you.

---

## What's NOT in the public API

These are internal helpers — they may change without notice:

- `fetcher._format`, `fetcher._peek_first_line`, `fetcher._scan`
- `parser.ARTICLE_TITLE_RE`, `parser.SECTION_RE`, `parser.URL_RE`
- `parser._TEMPLATE_PLACEHOLDER_RE`
- `extractor._PROMPT_HEADER_RE`, `_RESPONSE_HEADER_RE`, `_FAILEDPREFIX_RE`
- `renderer._ARTICLE_HTML`
- `dedup._TRACKING_PARAMS`, `_TRACKING_PREFIXES`

If you find yourself reaching for these, consider whether the public API
covers your use case. If not, file an issue — we may want to formalize
the helper.

---

## Versioning

This package uses semantic versioning. v0.x → breaking changes may happen
between minor versions. v1.0+ → semver guarantees apply.

Currently `0.2.0` (per `pyproject.toml`). See [`CHANGELOG.md`](../../CHANGELOG.md)
for version history.