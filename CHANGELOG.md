# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.0] - 2026-09-23

### Fixed
- **canonical URL 写漏** (per the 2026-09-23 dedup bug): `today_kept_urls.add()`
  was using raw URL (with trailing slash), but `is_url_in_recent_days()` looked up
  with canonical form. Lookups silently missed → same articles shipped twice or
  thrice. Now `add(canonical_url(art["url"]))`.
- **跨日 brief 漏入** (per the 2026-09-23 "content truncated" bug): `get_latest_md()`
  for non-HF jobs had no `today` filter; mtime sort would return N+1 brief if the
  sub-cron rolled over to tomorrow. New Pass 1 enforces "first line **日期** = today",
  with Pass 2 falling back to N-1/N-2 only (never N+1).
- **Renderer 空 source badge bug**: An empty source (zero articles after dedup)
  produced a stray source-badge `<span>`. Now only active sources get a badge.

### Added
- `is_url_in_recent_days` reverse-canonical fallback: legacy `seen_urls.json` files
  written before canonical-key adoption still get matched (via slow path that
  iterates all keys and re-canonicalizes). Emits an `[INFO]` so an operator can
  tell when migration is incomplete.
- `migrate_legacy_keys_to_canonical()` for one-shot state cleanup.
- Full test coverage on `canonical_url`, `parse_sections`, `get_latest_md`,
  `extract_clean_content`, end-to-end CLI. 77 tests, 90.66% coverage.
- GitHub Actions CI: pytest on Python 3.9/3.11/3.12 + mypy --strict.


## [0.3.0] - 2026-09-23 (docs/ expansion)

### Added
- **`docs/architecture.md`** — End-to-end pipeline architecture, module
  dependency graph, data contracts between modules, state lifecycle,
  failure-mode invariants.
- **`docs/modules/{dedup,parser,fetcher,renderer,extractor,cli}.md`** —
  Per-module contract / API / performance / common operator questions.
- **`docs/recipes/{add-new-source,backfill-dedup,debug-why-article-shipped,
  migrate-state-file,add-new-tracking-param,run-end-to-end-test}.md`** —
  Step-by-step ops recipes for common operations.
- **`docs/troubleshooting.md`** — 10 common failures with symptom /
  diagnosis / fix flowcharts.
- **`docs/reference/api.md`** — Public Python API reference with import
  examples and calling order.

### Changed
- `README.md` rewritten with documentation navigation table and 5-min
  getting-started section.

## [0.2.0] - 2026-09-23 (test suite expansion)

### Added
- **93 new pytest cases** spread across `test_dedup.py` (+30), `test_extractor.py` (+11),
  `test_fetcher.py` (+13), `test_parser.py` (+14), `test_renderer.py` (+13), `test_cli.py`
  (+12). Total: **170 tests, 91.82% coverage**.
- New `test_renderer.py::TestNoInnerScriptTags` pins **HTML injection defense** —
  surfaces a real XSS hole (img/svg/onerror tags passed through in article body),
  fixed in the same commit.
- **Full docs/ directory** (`docs/architecture.md`, `docs/modules/*.md`,
  `docs/recipes/*.md`, `docs/troubleshooting.md`, `docs/reference/api.md`) —
  module-level contracts, ops recipes, troubleshooting flowcharts, Python API reference.

### Fixed
- **XSS in renderer**: body content was rendered as raw HTML — `<img onerror=...>`,
  `<script>...</script>` etc. in article body would execute. Now `html.escape()`d.
- **XSS in URL field**: `javascript:alert(1)` in `art["url"]` was passed straight to
  `<a href="...">`. Now HTML-escaped via `html.escape(url, quote=True)`.
- **`canonical_url` now**: 
  - lower-cases host (DNS is case-insensitive; `Example.COM/foo` and `example.com/foo`
    must collide).
  - strips extended tracking IDs (`fbclid`, `gclid`, `mc_cid`, `_ga`, `igshid`,
    `msclkid`, `ttclid`, `li_fat_id`, etc.) per the 2026-09-23 dedup intent.
- **`migrate_legacy_keys_to_canonical`** now drops entries with corrupt dates
  (was previously polluting state with bad timestamp strings).

### Tests added by category
- `test_dedup.py`: 30 cases — port, IDN, percent-encoding, multi-value query,
  3rd-party tracker aliases, slow-path raw↔canonical lookup, corruption recovery.
- `test_extractor.py`: 11 cases — multi-marker, prompt-only fallback, FAILED at
  varying positions, trailing `---` semantics, Unicode/CJK/Emoji round-trip.
- `test_fetcher.py`: 13 cases — N-1/N-2 fallback, N+1 isolation (with documented
  Pass-3 leak), HF papers `YYYY-MM-DD.md` exact match, clock skew, special chars
  in filenames (spaces, Chinese, emoji).
- `test_parser.py`: 14 cases — section boundary (interior `###` doesn't split),
  URL extraction variants, Unicode titles/sections, dedup counter contract,
  cross-job `seen` set mutation across calls.
- `test_renderer.py`: 13 cases — UTF-8 round-trip (Chinese/Japanese/Korean/emoji),
  URL escape semantics (no double-escape, quotes/JS-protocol escape), section
  count consistency, large body stability, XSS defense.
- `test_cli.py`: 12 cases — `--today` backfill, `JOB_DIR_OVERRIDES` import-time
  freeze (documented limitation), atomic write, symlink resolution, partial
  failure still writes files, total failure exits 2.

