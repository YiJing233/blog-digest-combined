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
