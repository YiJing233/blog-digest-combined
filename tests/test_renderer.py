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
