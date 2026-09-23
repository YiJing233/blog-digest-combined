# `renderer` module

> Parse sections → Markdown + Kami-style HTML.

Source: `src/blog_digest_combined/renderer.py` (200 lines).

## Why this module exists

The rollup produces TWO output formats:
- **Markdown** (`blog_digest_YYYY-MM-DD.md`) — human-readable, also serves as
  raw input for Feishu doc notification.
- **HTML** (`blog_digest_YYYY-MM-DD.html`) — styled "Kami" theme; pushed
  to the user's Feishu/Telegram as the daily-digest doc.

Two output formats means two renderers, but they share `_article_body_html()`
to keep body-shape consistent.

## Public API

### `render_markdown(sources_data, today_str) -> str`

Per-source section assembly. Each source gets a `## <label>` heading;
each article becomes `### [title](url)` + body.

**Body markdown stripping**: HTML tags from `clean_body` are stripped back to
plain text (`re.sub(r"<[^>]+>", "", ...)`). The MD file is human-readable,
not browser-rendered.

**Output structure**:
```markdown
# 日报汇总 | 2026-09-23

共筛选自 4 个来源 · 27 篇精选

## iCloud 订阅

### [Foo Title](https://example.com/foo)

背景：...
核心观点：...

### [Bar Title](https://example.com/bar)
...

## Indie 科技
...
```

### `render_html(sources_data, today_str) -> str`

Full HTML document with:
- `<!DOCTYPE html>` + `<html lang="zh-CN">`
- Google Fonts (Inter + Newsreader + Noto Serif SC + JetBrains Mono)
- Kami CSS theme (`KAMI_CSS`)
- Article cards with `.article-inner`, `.article-accent`, `.article-body-text`
- Source badges in `.sources` div (only active sources — see filter)

**Output structure**:
```html
<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8">
  ...
  <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600&..." rel="stylesheet">
  <style>KAMI_CSS</style>
</head>
<body>
  <div class="page">
    <header class="doc-header">
      <h1 class="doc-title">日报汇总</h1>
      <div class="doc-meta">2026-09-23 · 27 篇精选</div>
      <div class="doc-desc">共筛选自 <span>4 个来源</span></div>
      <div class="sources">
        <span class="source-badge">iCloud 订阅</span>
        ...
      </div>
    </header>
    <main>
      <div class="section">
        <div class="section-header">
          <div class="section-title">🔬 技术深度</div>
          <div class="section-count">4 篇</div>
          <div class="section-rule"></div>
        </div>
        <div class="article">...</div>
      </div>
    </main>
    <footer class="footer">...</footer>
  </div>
</body>
</html>
```

### `render_article(art) -> str`

Public for direct rendering of a single article (e.g. in tests). Escapes:
- Title via `html.escape()`
- URL via `html.escape(url, quote=True)` — quote=True escapes `"` so JS
  protocol `javascript:alert(1)` becomes inert text

### `clean_body(raw)` (re-exported from `parser`)

Available at `blog_digest_combined.renderer.clean_body` for callers that
already imported `renderer` and don't want a separate `parser` import.

## Internal helpers

### `_article_body_html(art) -> str`

Per-article body rendering:
1. Iterate body lines
2. Skip `原文：https://...` line (URL extracted separately to `art["url"]`)
3. Skip `---` and `****` lines (Markdown separators)
4. Wrap each non-empty line in `<p>...</p>` with `html.escape()` (XSS defense)

Plus appends source-link footer:
```html
<div class="source-link">🔗 <a href="{url}" target="_blank">原文链接</a></div>
```

### `KAMI_CSS`

The full Kami-style CSS, ~60 lines. Custom properties for the canvas color
(`#f5f4ed`), ink color (`#1b365d`), serif headings (`Newsreader`),
Inter body, etc.

## XSS defense

Three layers of HTML escaping:
1. `html.escape(title)` — title in `<a>` text content
2. `html.escape(line)` — body text wrapped in `<p>`
3. `html.escape(url, quote=True)` — URL in `href` attribute

Without these, a malicious title or URL could inject `<script>` tags or
`javascript:` URLs. Pin: `TestNoInnerScriptTags` — found a real XSS hole
during the v0.2 test expansion.

**Found during testing**:
```python
{"title": "<script>alert(1)</script>",
 "url": "javascript:alert(2)",
 "body": "<img src=x onerror=alert(3)>"}
```
Before fix: all three would render as live HTML/JS.
After fix: all three are inert text.

## Empty source handling

A source with empty `sections` list (failed sub-cron, all dedup'd) gets:
- No `## <label>` header in Markdown output
- No `.section` div in HTML output
- No `.source-badge` for it

Pin: `test_empty_source_skipped` (MD) + `test_source_badges_shown` (HTML).

## Section count consistency

`{total_articles} 篇精选` in the doc-meta div MUST equal the sum of all
articles across all active sources.

Pin: `test_count_aggregates`.

If you add a new `sources_data` field, ensure it doesn't double-count.

## Performance

- 27 articles, 4 sources → ~5ms rendering
- 100 articles, 8 sources → ~20ms

Linear in articles. If you ever produce 1000+ articles per digest, the
bottleneck is the per-article `_ARTICLE_HTML.format()` call. Refactor to
join strings directly.

## Output file naming

Files are named `blog_digest_YYYY-MM-DD.{md,html}`. A symlink
`blog_digest_latest.html` points to today's HTML.

Pin: `test_md_and_html_per_today` + `test_symlink_points_to_today`.

## Common operator questions

### "Why does the HTML look different from the MD?"

Different output formats serve different purposes:
- **MD**: human-readable text, easy to edit by search-and-replace
- **HTML**: visual styling for Feishu/Telegram delivery

The body content is the same; the formatting differs by design.

### "The `<style>` block is huge. Can we externalize?"

Kami CSS is inlined so the HTML file is self-contained — no external
stylesheet dependency, no broken-link risk on delivery. If the file
becomes >1MB, externalize.

### "Why are source badges colored differently?"

They're not — they all use the same `.source-badge` class with
`background: var(--sand)`. The visual difference comes from the section
header rules, not the badges.

If you want per-source colors, add a `color` field to the source dict and
compute a CSS class for each.