# Architecture

How `blog-digest-combined` takes 4 sub-cron outputs and produces one deduplicated daily digest.

## High-level data flow

```
                    ┌─────────────────────────────────────────────────────┐
                    │                  ~/.hermes/cron/output/              │
                    │                                                       │
                    │   ae7df3150e0e/  909cbd821c57/  8836652e22cb/  hf... │
   (sub-cron 02:00- │       │              │             │              │    │
    03:50 UTC)      │       ▼              ▼             ▼              ▼    │
                    │   brief.md       brief.md      brief.md       brief.md │
                    └──────────┬──────────────────────────────────────────────┘
                               │
                               │   04:52 UTC: rollup cron fires
                               │   `python3 blog_digest_combined_wrapper.py`
                               ▼
                    ┌──────────────────────────────────────────────────────┐
                    │                    cli.main()                          │
                    │                                                          │
                    │   ┌─────────────────────────────────────────────┐        │
                    │   │         build_sources_data(today)            │        │
                    │   │                                                │        │
                    │   │  for each (label, job_id) in JOBS:            │        │
                    │   │   1. load_job_content(job_dir, today)         │        │
                    │   │      └── fetcher.get_latest_md(4-pass)        │        │
                    │   │      └── extractor.extract_clean_content()    │        │
                    │   │   2. parse_sections(                          │        │
                    │   │        content, today,                        │        │
                    │   │        recent_seen,    ◄────── dedup.py       │        │
                    │   │        cross_job_seen) ◄────── dedup.py       │        │
                    │   │   3. add art.url → today_canonical_urls       │        │
                    │   └─────────────────────────────────────────────┘        │
                    │                                                          │
                    │   if no articles kept across all jobs → exit 2           │
                    └──────────────────────────┬───────────────────────────────┘
                                               │
                                               │   sources_data: list[dict]
                                               ▼
                          ┌──────────────────────────────────────┐
                          │ renderer.render_html(sources_data)   │
                          │ renderer.render_markdown(...)        │
                          └──────────────────┬───────────────────┘
                                             │
                                             ▼
                    ┌──────────────────────────────────────────────────────┐
                    │  ~/.hermes/cron/output/combined/                       │
                    │                                                            │
                    │   blog_digest_YYYY-MM-DD.md     ◄─ human-readable MD       │
                    │   blog_digest_YYYY-MM-DD.html   ◄─ Kami-style HTML          │
                    │   blog_digest_latest.html       ◄─ symlink → today's HTML  │
                    │   seen_urls.json                ◄─ 跨日 dedup state        │
                    └──────────────────────────────────────────────────────┘
                                             │
                                             │   for main(): after HTML write
                                             ▼
                          ┌──────────────────────────────────────┐
                          │  mark today_canonical_urls as        │
                          │  today in seen_urls.json             │
                          │  (atomic write via save_seen_urls)   │
                          └──────────────────────────────────────┘
```

## Module dependency graph

```
        cli.py
        │
        ├── dedup.py       (load_seen_urls, save_seen_urls, canonical_url,
        │                   is_url_in_recent_days, evict_old_entries,
        │                   migrate_legacy_keys_to_canonical)
        │
        ├── fetcher.py     (get_latest_md 4-pass ladder, load_job_content,
        │                   extract_clean_content wrapper)
        │
        ├── extractor.py   (extract_clean_content: strip ## Prompt / ## Response)
        │
        ├── parser.py      (parse_sections, clean_body)
        │
        └── renderer.py    (render_html, render_markdown, render_article,
                            _article_body_html)
```

Modules **never import each other except via cli.py** — every module can be tested
in isolation. This is a deliberate choice: `pytest` runs `170` tests in `<1s` with
no module-import overhead.

## Data contracts between modules

| From → To | Type | Pin |
|------------|------|-----|
| fetcher → cli | `(content: str, mtime: str)` | `load_job_content` returns tuple; content is clean, mtime is ISO |
| parser → cli | `(sections, stats)` | `stats` keys = `{kept, cross_day_drops, cross_job_drops}` |
| cli → renderer | `sources_data: list[dict]` | Each entry has `{label, job_id, mtime, content, sections}` |
| renderer → disk | `(md_path, html_path)` | Files at `combined/blog_digest_{today}.{md,html}` |
| cli → dedup | `seen_urls.json: dict[str, str]` | `url → date (YYYY-MM-DD)` |

## State lifecycle

`seen_urls.json` is the **single source of truth** for cross-day deduplication.
Every cron run does exactly 2 mutations to it:

1. **Read** at the start of `build_sources_data` — load full file, evict entries
   older than `today - DEDUP_WINDOW_DAYS`, pass through to `recent_seen`.
3. **Write** at the end of `main()` — atomic write via `tmp + rename`. Replaces
   the whole file (not append-only). Always includes BOTH:
   - Previously-seen URLs within the window (unchanged date)
   - New today's URLs (added with `today`)

The eviction/rewrite pattern means:
- A URL that was first seen 5 days ago but is re-discovered today gets its date
  bumped to today (rolling window).
- A URL not seen for 4+ days falls off the end of the window.
- After a re-run with the same today, the date stays the same (idempotent).

## Failure-mode invariants

These invariants are pinned by `tests/test_*.py`. **Do not change without
updating the test that pins the invariant.**

### 1. N+1 brief never leaks into today's rollup

Pin: `tests/test_fetcher.py::TestNPlusOneIsolation::test_n_plus_1_alone_with_back_days_can_match_p3`

Even when sub-cron writes N+1 (tomorrow's brief) into the wrong directory, the
rollup's Pass 1 (`**日期**：<today>` exact match) and Pass 2 (N-1, N-2) **never
select N+1**. Pass 3 (lenient any-header) is the known-limitation — it can
match N+1 in absence of a better candidate, so the operator should warn when
Pass 3 fires.

### 2. Cross-day dedup never false-misses

Pin: `tests/test_dedup.py::TestIsUrlInRecentDaysDualKeyLookup`

`is_url_in_recent_days` does BOTH:
- **Fast path**: direct canonical lookup in `seen` dict
- **Slow path**: legacy-state recovery — if direct lookup misses, scan all keys
  in `seen`, re-canonicalize each, look for a match. Emits `[INFO] Migration in progress`
so operator can tell when state files are mis-aligned.

### 3. Cross-day content-truncation never happens (no N+1 brief ships)

Pin: `tests/test_fetcher.py::TestCrossDayBug` + `tests/test_parser.py::TestCleanBodyEdgeCases`

Article body MUST come from the today-brief file, not tomorrow's. The fetcher's
Pass 1+2 guarantee this; the parser never assembles articles from multiple files.

### 4. State file is always parseable

Pin: `tests/test_dedup.py::TestLoadSeenUrlsCorruptionRecovery`

- Empty file → `{}` (zero-byte, corrupted, only whitespace)
- Invalid JSON → `{}` (no exception, no panic)
- Top-level list `[1,2,3]` → `{}` (forbidden shape)
- `null` → `{}`

This protects against operator actions like `cat > seen_urls.json` mid-run.

### 5. Renderer escapes user content

Pin: `tests/test_renderer.py::TestNoInnerScriptTags`

Article body AND URL go through `html.escape()` — `<script>`, `<img onerror>`,
`javascript:` URLs all become inert text. (Found and fixed one XSS hole during
the v0.2 test expansion.)

## Design choices (and why)

### Why is the package so small (471 lines src)?

It's intentionally a thin glue layer between the 4 sub-cron outputs. The
complexity lives in:

- **`canonical_url()`** — single most-failed contract; 30+ tests pin edge cases
- **`get_latest_md()`** 4-pass ladder — 13 tests pin each pass
- **`parse_sections()`** — 14+ tests cover URL extraction variants

Each is small (~50 lines) but tightly specified. Adding code ≠ adding tests;
the bug surface area is concentrated in URL handling and date headers.

### Why no external dependencies?

`blog-digest-combined` runs in `no_agent=true` cron jobs (Hermes cron runtime
sometimes freezes imports for token savings). Stdlib-only means:
- No pip install on the host machine
- No version conflicts with the rest of Hermes
- `pip install -e ~/projects/blog-digest-combined` works everywhere

### Why a separate package instead of inlining?

- **Testability**: the in-tree `~/.hermes/scripts/blog_digest_combined.py` was
  a 747-line monolith with no tests. Splitting into modules let pytest cover
  170 distinct behaviors in <1s.
- **Versioning**: when `canonical_url` changes behavior, git history shows
  exactly which tests had to change (vs prose-pinning in a SKILL.md which
  has no enforcement).
- **Reuse**: the next cron project that needs URL canonicalization or
  multi-source dedup can `from blog_digest_combined.dedup import canonical_url`
  instead of copy-pasting.

### Why is the package stay so simple? (No plugin system, no config files)

This is a single-use tool, not a framework. Configuration comes from:
1. Constants in `cli.py` (`JOBS`, `DEDUP_WINDOW_DAYS`)
2. Layout convention (`~/.hermes/cron/output/<job_id>/`)
3. CLI args (`--today`, `--output-dir`)

If you find yourself adding a config file, you probably want a separate package.