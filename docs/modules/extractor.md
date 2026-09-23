# `extractor` module

> Strip prompt dumps and trailing notes from raw sub-cron output.

Source: `src/blog_digest_combined/extractor.py` (91 lines).

## Why this module exists

Sub-cron output looks like:

```
# Cron Job: iCloud 订阅源每日简报
## Prompt
... (50KB SKILL.md dump) ...
## Response
**日期**：2026-09-23
... actual summary ...
**执行备注**：...
```

Without the `## Response` extraction, the rollup would ship the SKILL.md
dump (50KB+ of irrelevant instructions) as part of the digest. This module
strips everything before `## Response` and trims trailing execution notes.

## Public API

### `extract_clean_content(raw_content: str) -> str`

**Returns**: clean content string (no prompt dump, no trailing notes).

**Failure modes**:
- Empty input → `""`
- `(FAILED)` on first line → `""` (whole-job failure, caller skips)
- Only `## Prompt` (no `## Response`) → returns everything after `## Prompt`
- Neither marker → returns input verbatim (legacy brief shape)

## Truncation rules

Trailing content trimmed by `_TRUNCATION_MARKERS`:
- `**执行备注` (Chinese execution notes marker)
- `（共筛选` (filter-count marker, half-width paren)
- `---` (Markdown separator)

Reverse loop finds the **last** matching line, truncates everything after.
Pin: `test_interior_dashes_kept_but_trailing_dropped`.

If a brief has interior `---` separators between paragraphs AND a trailing
`---`, the LAST one is the trim point; everything before stays. (Documented
behavior — if this becomes annoying, change the marker to `**END OF BRIEF**`.)

## `(FAILED)` job detection

`_FAILEDPREFIX_RE = re.compile(r"\(FAILED\)")`

Only checks **line 1** of the raw content. If `(FAILED)` appears on line 5
(e.g. mid-execution comment), it's not treated as a job failure.

Pin: `TestFailedMarkerPosition::test_failed_marker_with_chinese_context_does_not_truncate`

## Multiple `## Response` markers

The first non-code-fence `## Response` is the trim point. Pin:
`TestMultipleResponseMarkers::test_multiple_response_markers_take_first`.

Sub-cron agents sometimes mention `## Response` in their prompt text as a
sentinel. Code fences containing the literal `## Response` are skipped by
the in-code-fence check.

## Code-fence awareness

`## Prompt` / `## Response` markers inside ``` code fences are ignored.
This is critical because sub-cron prompts often include a literal `## Response`
as an example of what they should NOT do.

## Exported constants (used by `fetcher.py`)

```python
REAL_BRIEF_HEADER_RE = re.compile(r"^\*\*日期\*\*\s*[：:]")
DATE_HEADER_RE      = re.compile(r"^\*\*日期\*\*[：:]\s*(\d{4}-\d{2}-\d{2})")
RAW_DEBUG_HINT_RE   = re.compile(r"^#\s*Cron Job:|^##\s*Prompt\s*$", re.MULTILINE)
MAX_REAL_BRIEF_BYTES = 50 * 1024  # raw debug logs are 70-130KB
```

These are the "is this a real brief?" filters:
- `REAL_BRIEF_HEADER_RE` — line 1 starts with `**日期**:` (any separator)
- `DATE_HEADER_RE` — line 1 has `**日期**：YYYY-MM-DD` (strict date capture)
- `RAW_DEBUG_HINT_RE` — anywhere in first 2KB, has `# Cron Job:` or `## Prompt`
- `MAX_REAL_BRIEF_BYTES` — file size filter

Used by `fetcher.get_latest_md` Pass 3/4 to discriminate "real brief" from
"raw debug log".

## Performance

- 50KB input → ~10ms (single linear scan)
- 100KB input → ~20ms

Linear scans are unavoidable here since we have to walk all lines to find the
right trim points.

## Edge cases pinned

| Input | Output | Test |
|-------|--------|------|
| Empty | `""` | implicit |
| `(FAILED)` first line | `""` | `test_failed_on_first_line` |
| `(FAILED)` mid-content | comment in mark | `test_failed_marker_with_chinese_context_does_not_truncate` |
| `## Prompt` only (no `## Response`) | from `## Prompt+1` | `test_prompt_only_no_response` |
| Neither marker | as-is | `test_no_prompt_marker_either` |
| Multiple `## Response` | first one | `test_multiple_response_markers_take_first` |
| `## Response` in code fence | ignored | `test_response_in_prompt_text_only_no_real` |
| Interior `---` + trailing `---` | last `---` is trim | `test_interior_dashes_kept_but_trailing_dropped` |
| CJK + emoji + em-dash | all preserved | `TestUnicodeAndCjk` |

## Why not use a real Markdown parser?

`markdown-it-py` / `mistune` / `commonmark-py` would be more robust, but:
- Pulls in a dep (we're stdlib-only by design)
- The input format is constrained — we know the structure ahead of time
- Linear scan is fast enough at <100KB input sizes
- The bugs we pin (trailing `---`, `(FAILED)` detection) are *format-specific*
  concerns that a generic parser wouldn't help with

If the format ever becomes arbitrarily structured, swap to a real parser.