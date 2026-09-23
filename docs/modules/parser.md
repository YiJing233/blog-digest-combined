# `parser` module

> Markdown → sections/articles parser. The core of the rollup.

Source: `src/blog_digest_combined/parser.py` (155 lines).

## Input format

A blogwatcher cron output looks like:

```
**日期**：2026-09-23

## 🔬 技术深度

**[1] Foo Title**
原文：https://example.com/foo

背景：...
核心观点：...

---

**[2] Bar Title**
原文：https://www.example.com/bar?fbclid=x

背景：...
```

This gets split into sections (per `## title` heading) and articles (per `**[N] title**`).

## Public API

### `parse_sections(text, today, recent_seen=None, cross_job_seen=None, window_days=3)`

**Returns**: `(sections, stats)`

`sections` shape:
```python
[
  {
    "title": "🔬 技术深度",  # str from `## heading`
    "articles": [
      {
        "title": "Foo Title",  # from **[1] Foo Title**
        "num": "1",             # str (NOT int — preserves "001" zero-padding if present)
        "body": "...",             # cleaned body, paragraphs preserved
        "url": "https://...",    # first URL match in body
      },
      ...
    ],
  },
  ...
]
```

`stats` shape:
```python
{
  "cross_day_drops":  5,   # URLs already in seen_urls.json (last 3 days)
  "cross_job_drops":  2,   # URLs kept by earlier sub-cron in THIS run
  "kept":             18,  # total articles surviving dedup
}
```

**Args**:
- `text`: full cleaned brief content (output of `extract_clean_content`)
- `today`: ISO date `YYYY-MM-DD`
- `recent_seen`: optional `dict[canonical_url → "YYYY-MM-DD"]` from `seen_urls.json`
- `cross_job_seen`: optional `set[str]` of canonical URLs already kept by earlier sub-crons this execution
- `window_days`: dedup window (default 3, matches `cli.DEDUP_WINDOW_DAYS`)

**Mutation semantics**:
- `cross_job_seen` is mutated in-place — caller passes the same set across
  multiple `parse_sections` calls (one per sub-cron). This is the only way
  cross-job dedup works.
- `recent_seen` is NOT mutated — caller owns the seen_urls state lifecycle.

**Dedup logic** (in order, for each article):
1. Extract URL from body via `URL_RE.search()` — first match wins
2. Skip if URL empty OR contains `{` / `}` (template placeholder leak)
3. Canonicalize URL via `canonical_url`
4. Cross-day check: `is_url_in_recent_days(canonical, recent_seen, today, window_days)` → drop
5. Cross-job check: `canonical in cross_job_seen` → drop
6. Add `canonical` to `cross_job_seen` (mutates caller state)
7. Keep article

## URL extraction

`URL_RE = re.compile(r'https?://[^\s\)\]\"\'<>]+')`

Matches any HTTP(S) URL up to the first non-URL character:
- Whitespace
- `)` `]` (Markdown link closing parens)
- `"` `'` (HTML/quote contexts)
- `<` `>` (HTML angle brackets)

**Pinned cases** (each in `test_parser.py::TestUrlExtractionVariants`):
| Form | Test |
|------|------|
| Bare `原文：https://...` | implicit (the common case) |
| Markdown link `[text](https://...)` | `test_url_in_markdown_link_format` |
| Wrapped in parens `(https://...)` | `test_url_inside_parentheses` |
| With query params `?key=val` | `test_url_with_query_params` |

## Template placeholder handling

`_TEMPLATE_PLACEHOLDER_RE = re.compile(r"[{}]")`

Any URL containing `{` or `}` is silently dropped. Pin: `test_should_prompt_only_no_url_is_dropped`
in `tests/test_parser.py`.

**Why this exists**: blogwatcher sub-cron prompts include `原文：{URL}`
or `https://example.com/{slug}`. If an LLM agent forgets to substitute the
variable, the parsed URL becomes `{URL}` or `https://example.com/{slug}`.
Without this filter, the literal string would get canonicalized and written
to `seen_urls.json` — polluting state with garbage.

## Body cleanup

`clean_body(raw)` — run on the article body before returning.

Operations:
- `**bold**` → `<strong>bold</strong>`
- `*em*` → `<em>em</em>`  (after the `**` substitution, so `**a*b**` doesn't get mangled)
- `` `code` `` → `<code>code</code>`
- `[link](url)` → `link` (URL stripped; `render_article` adds it back via `art["url"]`)
- `- foo` / `* foo` → `• foo`
- Trim leading/trailing whitespace per line

**Pinned** (in `test_parser.py::TestCleanBodyEdgeCases`):
- Paragraph breaks preserved (test `test_preserves_paragraph_breaks`)
- Strong/em/code transformations don't double-apply

## Constants (exported)

```python
ARTICLE_TITLE_RE = re.compile(r'^\*\*\[(\d+)\]\s*(.+?)\*\*\s*$')
SECTION_RE = re.compile(r'^##\s+(.+)$')
URL_RE = re.compile(r'https?://[^\s\)\]\"\'<>]+')
_TEMPLATE_PLACEHOLDER_RE = re.compile(r"[{}]")
```

`ARTICLE_TITLE_RE` requires the line to start with `**[N]` where N is digits.
A title with brackets but no `**[N]` prefix (e.g. `**【这是一篇中文文章】**`)
also matches — the `(.+?)` group captures the title text, regardless of CJK.

## Section boundaries

A new section starts on `## title` (one `#`, NOT two).

`### subheading` inside an article body is **NOT** a section boundary — it stays
as part of the previous article. Pin: `test_articles_with_subsections_dont_split`.

This matches the blogwatcher convention where `### ...` is content depth-marker,
not taxonomy depth-marker.

## Edge cases (each pinned)

| Input | Output | Test |
|-------|--------|------|
| Empty string | `[]`, `kept=0` | `test_completely_empty` |
| Header only, no articles | `[]` (empty sections dropped) | `test_only_header_no_articles` |
| Article without URL | dropped (silently) | `test_article_without_url_dropped` |
| Two sections no blank lines between | 2 sections | `test_consecutive_sections_no_blank_lines` |
| `### subheading` inside body | stays as body content | `test_articles_with_subsections_dont_split` |
| Unicode emoji in section title | preserved | `test_section_with_emoji` |
| CJK brackets in title | preserved | `test_title_with_chinese_brackets` |
| Same URL in two consecutive parses | second call drops it | `test_set_grows_across_calls_and_dedups_next_call` |

## Stats counter contract

`stats` keys MUST be exactly `{"kept", "cross_day_drops", "cross_job_drops"}`.
Pin: `test_stats_keys_present`.

If you add a new counter, add it to `test_stats_keys_present` as well —
operators read these from CLI output.

## Performance

- Parse ~10KB brief → ~5ms
- Parse ~50KB brief → ~30ms
- 4 sub-crons, ~150 articles total → ~50ms total parsing

If briefs grow past 100KB, the regex pass on each line becomes the
bottleneck. Refactor to a single-pass state machine instead of `re.match`
per line.

## Why a separate module?

The dedup logic in `parse_sections` is small (~30 lines) but its correctness
is critical. Splitting it out lets pytest:
- Pass different `recent_seen` and `cross_job_seen` fixtures per test
- Pin specific edge cases (template leaks, missing URLs, slow-path
  legacy-state recovery) without involving the file I/O machinery
- Run all parser tests in 0.05s — 170 tests total <1s.