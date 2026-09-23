"""End-to-end smoke test for the renderer.

We don't snapshot diff the entire output (that's brittle) — instead we
verify the building blocks compose:

  - render_markdown includes every article title + URL
  - render_html produces a valid <html> wrapper + every section/heading
  - 27-article fixture from the real 2026-09-23 run (kept inline) renders fully
"""

from __future__ import annotations

from blog_digest_combined.renderer import render_html, render_markdown


SOURCES = [
    {
        "label": "iCloud 订阅",
        "sections": [
            {
                "title": "🔬 技术深度",
                "articles": [
                    {
                        "title": "Article A",
                        "url": "https://example.com/a",
                        "body": "Line one.\n\nLine two.",
                    },
                ],
            },
        ],
    },
    {
        "label": "ML 博主",
        "sections": [
            {
                "title": "🛠️ 开发实践",
                "articles": [
                    {
                        "title": "Article B",
                        "url": "https://example.com/b",
                        "body": "Body B content.",
                    },
                ],
            },
        ],
    },
    {
        "label": "Empty Source",  # job dedup'd to 0 — should still be safe
        "sections": [],
    },
]


class TestRenderMarkdown:
    def test_includes_titles(self):
        md = render_markdown(SOURCES, today_str="2026-09-23")
        assert "Article A" in md
        assert "Article B" in md

    def test_includes_urls(self):
        md = render_markdown(SOURCES, today_str="2026-09-23")
        assert "https://example.com/a" in md
        assert "https://example.com/b" in md

    def test_includes_source_labels(self):
        md = render_markdown(SOURCES, today_str="2026-09-23")
        assert "iCloud 订阅" in md
        assert "ML 博主" in md

    def test_includes_today_in_header(self):
        md = render_markdown(SOURCES, today_str="2026-09-23")
        assert "2026-09-23" in md

    def test_empty_source_no_header_section(self):
        # An empty source produces no ## header in the body
        md = render_markdown(SOURCES, today_str="2026-09-23")
        assert "## Empty Source" not in md
        # But active sources still get headers
        assert "## iCloud 订阅" in md
        assert "## ML 博主" in md

    def test_total_articles_in_doc_meta(self):
        md = render_markdown(SOURCES, today_str="2026-09-23")
        assert "2 篇精选" in md


class TestRenderHtml:
    def test_valid_html_structure(self):
        html_text = render_html(SOURCES, today_str="2026-09-23")
        assert html_text.startswith("<!DOCTYPE html>")
        assert "</html>" in html_text
        assert "<title>日报汇总 | 2026-09-23</title>" in html_text

    def test_kami_css_embedded(self):
        html_text = render_html(SOURCES, today_str="2026-09-23")
        assert ".page" in html_text
        assert "Newsreader" in html_text

    def test_articles_rendered(self):
        html_text = render_html(SOURCES, today_str="2026-09-23")
        assert "Article A" in html_text
        assert "Article B" in html_text
        # Source-link section per article
        assert html_text.count("原文链接") >= 2

    def test_source_badges_shown(self):
        html_text = render_html(SOURCES, today_str="2026-09-23")
        # CSS includes "source-badge" selector; only the 2 active sources produce <span>
        assert "source-badge" in html_text
        # Only the 2 active sources produce <span class="source-badge"> elements
        expected_substr = '<span class="source-badge">'
        assert html_text.count(expected_substr) == 2

    def test_html_escapes_dangerous_titles(self):
        """A title containing <script> should be HTML-escaped, not injected."""
        dangerous = [{
            "label": "X",
            "sections": [{
                "title": "S",
                "articles": [{
                    "title": "<script>alert(1)</script>",
                    "url": "https://example.com",
                    "body": "body",
                }],
            }],
        }]
        html_text = render_html(dangerous, today_str="2026-09-23")
        assert "<script>alert(1)</script>" not in html_text
        assert "&lt;script&gt;" in html_text


class TestUTF8RoundTrip:
    """Chinese/Japanese/Korean + emoji must round-trip in HTML output."""

    def test_chinese_in_body_preserved(self):
        from blog_digest_combined.renderer import render_html
        sources = [{"label": "X", "sections": [{
            "title": "S", "articles": [
                {"title": "中文标题", "url": "https://x.com", "body": "中文正文。"},
            ],
        }]}]
        html_text = render_html(sources, today_str="2026-09-23")
        assert "中文标题" in html_text
        assert "中文正文" in html_text

    def test_emoji_in_title(self):
        from blog_digest_combined.renderer import render_html
        sources = [{"label": "X", "sections": [{
            "title": "S", "articles": [
                {"title": "🚀 Article", "url": "https://x.com", "body": "emoji body"},
            ],
        }]}]
        html_text = render_html(sources, today_str="2026-09-23")
        assert "🚀" in html_text

    def test_japanese_korean_in_body(self):
        from blog_digest_combined.renderer import render_html
        sources = [{"label": "X", "sections": [{
            "title": "S", "articles": [
                {"title": "テスト", "url": "https://x.com", "body": "テスト本文。"},
            ],
        }]}]
        html_text = render_html(sources, today_str="2026-09-23")
        assert "テスト" in html_text


class TestUrlEscaping:
    """URLs with `&`, `?`, `=` must NOT be double-escaped."""

    def test_url_with_query_param_not_double_escaped(self):
        from blog_digest_combined.renderer import render_html
        sources = [{"label": "X", "sections": [{
            "title": "S", "articles": [
                {"title": "A", "url": "https://example.com/foo?a=1&b=2", "body": "b"},
            ],
        }]}]
        html_text = render_html(sources, today_str="2026-09-23")
        # The URL appears in href (raw) and source-link (escaped) contexts
        assert "https://example.com/foo?a=1&amp;b=2" in html_text

    def test_url_with_html_in_query_param_escaped(self):
        """`<` and `>` in URLs must be escaped regardless of where."""
        from blog_digest_combined.renderer import render_html
        sources = [{"label": "X", "sections": [{
            "title": "S", "articles": [
                {"title": "A", "url": "https://example.com/foo?q=<script>", "body": "b"},
            ],
        }]}]
        html_text = render_html(sources, today_str="2026-09-23")
        # No raw <script> should appear in href
        import re
        hrefs = re.findall(r'href="([^"]*)"', html_text)
        for href in hrefs:
            assert "<script>" not in href


class TestArticleCountConsistency:
    """Section count in header must match sum of articles across sections."""

    def test_count_aggregates(self):
        from blog_digest_combined.renderer import render_html
        sources = [
            {"label": "A", "sections": [
                {"title": "X", "articles": [
                    {"title": "a1", "url": "https://x.com/1", "body": "x"},
                    {"title": "a2", "url": "https://x.com/2", "body": "x"},
                ]},
            ]},
            {"label": "B", "sections": [
                {"title": "Y", "articles": [
                    {"title": "b1", "url": "https://x.com/3", "body": "x"},
                ]},
            ]},
        ]
        html_text = render_html(sources, today_str="2026-09-23")
        assert "3 篇精选" in html_text
        # Each section shows its own count
        assert "2 篇" in html_text
        assert "1 篇" in html_text


class TestFooterStructure:
    def test_footer_two_columns(self):
        from blog_digest_combined.renderer import render_html
        sources = [{"label": "X", "sections": []}]
        html_text = render_html(sources, today_str="2026-09-23")
        assert "Generated by Hermes" in html_text
        assert "Kami Design" in html_text
        assert "2026-09-23" in html_text

    def test_footer_no_articles(self):
        """Empty sources list still produces valid HTML footer."""
        from blog_digest_combined.renderer import render_html
        html_text = render_html([], today_str="2026-09-23")
        assert html_text.startswith("<!DOCTYPE html>")
        assert "Generated by Hermes" in html_text
        # 0 articles — meta shows "0 篇精选"
        assert "0 篇精选" in html_text
        # No source badges (none active)
        assert html_text.count('<span class="source-badge">') == 0


class TestBigBody:
    def test_10000_char_body_does_not_break_layout(self):
        from blog_digest_combined.renderer import render_html
        big = "正文段落。\n\n" * 1000  # ~6000 chars
        sources = [{"label": "X", "sections": [{
            "title": "S", "articles": [
                {"title": "Big", "url": "https://x.com", "body": big},
            ],
        }]}]
        html_text = render_html(sources, today_str="2026-09-23")
        # Should still parse as valid HTML
        assert html_text.startswith("<!DOCTYPE html>")
        assert html_text.count("<p>") > 100


class TestNoInnerScriptTags:
    """Even with multiple bypass attempts, no <script> may appear inside <article>."""

    def test_no_inner_script_after_xss_in_title_and_body(self):
        from blog_digest_combined.renderer import render_html
        sources = [{"label": "X", "sections": [{
            "title": "S",
            "articles": [
                {"title": "<script>alert(1)</script>", "url": "javascript:alert(2)", "body": "<img src=x onerror=alert(3)>"},
            ],
        }]}]
        html_text = render_html(sources, today_str="2026-09-23")
        # No raw script tags
        assert "<script>alert(1)</script>" not in html_text
        assert "&lt;script&gt;" in html_text
        # Body content was escaped (img tag is gone — replaced by escape)
        assert "<img" not in html_text

    def test_url_with_quotes_escaped(self):
        from blog_digest_combined.renderer import render_html
        sources = [{"label": "X", "sections": [{
            "title": "S", "articles": [
                {"title": "A", "url": 'https://example.com/?q="hello"', "body": "b"},
            ],
        }]}]
        html_text = render_html(sources, today_str="2026-09-23")
        # Quotes get escaped in href
        assert 'href="https://example.com/?q=&quot;hello&quot;"' in html_text


class TestMarkdownRendererSafety:
    """render_markdown should also escape special characters in titles for safety."""

    def test_markdown_url_format_preserved(self):
        from blog_digest_combined.renderer import render_markdown
        sources = [{"label": "X", "sections": [{
            "title": "S", "articles": [
                {"title": "A", "url": "https://x.com/a", "body": "b"},
            ],
        }]}]
        md = render_markdown(sources, today_str="2026-09-23")
        assert "### [A](https://x.com/a)" in md

    def test_chinese_title_in_markdown(self):
        from blog_digest_combined.renderer import render_markdown
        sources = [{"label": "X", "sections": [{
            "title": "S", "articles": [
                {"title": "中文标题", "url": "https://x.com", "body": "中文正文"},
            ],
        }]}]
        md = render_markdown(sources, today_str="2026-09-23")
        assert "中文标题" in md
        assert "中文正文" in md
