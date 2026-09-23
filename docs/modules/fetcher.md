# `fetcher` module

> Pick the right sub-cron output for today's rollup. Today-bound; never picks N+1.

Source: `src/blog_digest_combined/fetcher.py` (167 lines).

## Why this module exists

The 2026-09-23 "content truncated" bug. Symptom: user reported "some sections
are short, some articles have no body". Root cause: when sub-cron at 03:50
produced a N+1 (tomorrow's) brief into the same directory, `get_latest_md`
picked whatever had the highest mtime — could be the N+1 brief. Rendered
output's body was from tomorrow, but filename said today → "truncated".

The fix: **Pass 1 requires `**日期**：<today>` exact match**. Only when that
fails do we accept N-1 / N-2 fallback. Never N+1.

## Public API

### `get_latest_md(job_dir, today=None, allow_back_days=2)`

The 4-pass (well, 6-pass counting Pass 0) selection ladder.

**Selection priority** (highest priority first):

| Pass | Match condition | Why this pass exists |
|------|-----------------|----------------------|
| **0** | `{today}.md` exists (exact filename) | HF papers cron uses this convention |
| **1** | `**日期**：<today>` on first line | Today's brief, regardless of filename |
| **2** | `**日期**：<today-1>` or `<today-2>` | Sub-cron ran late |
| **3** | Any `**日期**：YYYY-MM-DD` header + <50KB | `today` not specified (debug) |
| **4** | File <50KB AND no `## Prompt` header | Real brief, but date stripped |
| **5** | mtime-descending (any file) | Last-resort fallback |

**Args**:
- `job_dir`: path to sub-cron output dir (e.g. `~/.hermes/cron/output/ae7df3150e0e/`)
- `today`: ISO date string `YYYY-MM-DD` — required for Pass 1/2 to fire
- `allow_back_days`: int >= 0, controls Pass 2 reach. `0` disables N-1/N-2 fallback.

**Returns**: `(relative_path, mtime_str)` or `(None, None)` if dir empty.

**Behavior pins** (each pinned by a test):
- Pass 1 + existing today file → today file wins (test `TestCrossDayBug`)
- Pass 2 + N-1 only → N-1 file picked (`test_fallback_to_yest_when_today_missing`)
- Pass 2 + N-2 only → N-2 file picked (`test_fallback_to_n_minus_2`)
- Pass 3 NEVER matches N+1 (with back_days=0, today strict) — documented limitation
  in `test_n_plus_1_alone_with_back_days_can_match_p3`
- Pass 4 fires on brief with no `**日期**` header (`test_brief_under_50kb_with_real_header`)
- Pass 5 only fires when Pass 1-4 all fail (`TestClockSkewAcrossMidnight`)

**Why 4 passes (not just "today or nothing")**:
Real-world cron pipeline has many failure modes:
- Sub-cron may run 5min late → produce N-1 brief, not today
- Manual edits may strip the date header → Pass 4 catches it
- Debug logs may have valid brief + a debug dump alongside → Pass 4 size filter
- Network errors during sub-cron retry → brief from N-2 still valid
- mtime clock skew (rare) → Pass 5 mtime sort is the last-resort answer

### `load_job_content(job_dir, today=None) -> (str, str)`

Convenience wrapper: calls `get_latest_md`, then `extract_clean_content`.

Returns `(clean_text, mtime_str)`. Empty `clean_text` means the job failed
(no brief or no usable content).

Used by `cli.main()` as the entry point per sub-cron.

## Internal helpers (private)

### `_format(path) -> (Optional[str], Optional[str])`

`path → (path_str, "YYYY-MM-DD HH:MM")` or `(None, None)`.

Centralizes mtime formatting so `get_latest_md` doesn't repeat the
`datetime.fromtimestamp(...).strftime(...)` pattern at every pass return.

### `_peek_first_line(path) -> Optional[str]`

First line of file, stripped. Reads up to OS-buffer-size. Returns `None` on
`OSError`. Used by Pass 1/2/3 to scan date headers without loading the full
file.

### `_scan(md_files, pattern, target_value)`

Iterate `md_files` (already mtime-sorted desc), return first match where
the first line's regex capture group == `target_value`.

The `pattern` arg decouples this helper from the specific DATE_HEADER_RE —
it's also used for `REAL_BRIEF_HEADER_RE` in Pass 3.

## Constants

These come from `extractor.py` (imported at module level):

- `DATE_HEADER_RE` — matches `**日期**：YYYY-MM-DD` exactly
- `REAL_BRIEF_HEADER_RE` — matches any `**日期**：...` header
- `MAX_REAL_BRIEF_BYTES = 50 * 1024` — files ≥ 50KB are debug logs
- `RAW_DEBUG_HINT_RE` — matches `## Prompt` to flag agent-debug files

## Operator warning for Pass 3 leakage

When the only briefs in a job dir are N+1, Pass 3 will pick one. Print:

```
[WARN] get_latest_md(ae7df3150e0e): today=2026-09-23 → only N+1 briefs found,
       Pass 3 leniency selected 2026-09-24. Operator should investigate.
```

If you see this in cron logs, the sub-cron is broken (or the date math is).
Fix is on the sub-cron side — re-run it manually or wait for the next retry.

## Performance

- 1 brief in dir: ~1ms (one stat + one read)
- 10 briefs: ~10ms (10x stats + first-line reads)
- 50 briefs: ~50ms (still well under the 60s cron deadline)

If `job_dir` ever grows past 100 briefs, the mtime sort + first-line scan
becomes the bottleneck. Refactor to read all headers once into a list.

## Common operator questions

### "Why didn't Pass 1 match?"

Three common causes:
1. **Header format changed**: sub-cron now uses `**日期：**` (full-width colon)
   instead of `**日期**:` (half-width). Check by reading the brief directly:
   ```bash
   head -1 ~/.hermes/cron/output/ae7df3150e0e/2026-09-23.md
   ```
2. **Sub-cron wrote a debug dump as the first line**: e.g. `Failed to fetch: ...`
   Solution: re-run sub-cron.
3. **Different file than expected**: sub-cron wrote to a new file with
   `2026-09-23_04-12.md` (timestamped). Pass 0 only matches `{today}.md`
   literally; Pass 1 matches the date header which IS in such a file.

### "Why did Pass 3 fire when today is specified?"

Pass 3 only fires when Pass 1 + Pass 2 both failed. If Pass 3 picked an
N+1 brief, that's documented as a known-limitation (see test
`test_n_plus_1_alone_with_back_days_can_match_p3`). The right fix is on
the sub-cron side — clean up stale N+1 briefs.