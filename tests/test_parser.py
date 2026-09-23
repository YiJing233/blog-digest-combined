"""Tests for markdown section/article parser.

Pins two regressions:
  - parse_sections: cross-day dedup uses canonical keys (2026-09-23 bug #1)
  - parse_sections: cross-job dedup is hard (🔁 soft-dedup was a silent failure)
"""

from __future__ import annotations

import pytest

from blog_digest_combined.parser import clean_body, parse_sections


# ── Sample markdown fixture ────────────────────────────────────

SAMPLE_MD = """**日期**：2026-09-23

## 🔬 技术深度

**[1] Foo 文章**
原文：https://example.com/foo

背景：foo 的背景
核心观点：foo 的核心
意义：foo 的意义

---

**[2] Bar 文章**
原文：https://example.com/bar

背景：bar 的背景

---

## 🏢 产业动态

**[3] Baz 文章**
原文：https://example.com/baz

背景：baz 的背景

"""


class TestParseSectionsBasic:
    def test_returns_two_sections(self):
        sections, stats = parse_sections(SAMPLE_MD, today="2026-09-23")
        assert len(sections) == 2
        assert "技术深度" in sections[0]["title"]
        assert "产业动态" in sections[1]["title"]

    def test_articles_in_order(self):
        sections, _ = parse_sections(SAMPLE_MD, today="2026-09-23")
        arts = sections[0]["articles"]
        assert [a["title"] for a in arts] == ["Foo 文章", "Bar 文章"]
        assert [a["num"] for a in arts] == ["1", "2"]

    def test_url_extracted_to_field(self):
        sections, _ = parse_sections(SAMPLE_MD, today="2026-09-23")
        for art in sections[0]["articles"]:
            assert art["url"].startswith("https://")
            assert art["url"] in (
                "https://example.com/foo", "https://example.com/bar",
            )


class TestCrossDayDedup:
    """The 2026-09-23 dedup bug."""

    def test_known_recent_url_dropped(self):
        recent = {"https://example.com/foo": "2026-09-22"}
        sections, stats = parse_sections(
            SAMPLE_MD, today="2026-09-23", recent_seen=recent,
        )
        assert stats["cross_day_drops"] == 1
        # Foo (yesterday) gone; Bar (never seen) kept
        kept_urls = [a["url"] for s in sections for a in s["articles"]]
        assert "https://example.com/foo" not in kept_urls
        assert "https://example.com/bar" in kept_urls

    def test_three_day_window(self):
        # URL last seen 3 days ago → still in 3-day window → drop
        recent = {"https://example.com/foo": "2026-09-20"}
        sections, stats = parse_sections(
            SAMPLE_MD, today="2026-09-23", recent_seen=recent, window_days=3,
        )
        assert stats["cross_day_drops"] == 1

    def test_four_days_outside_window(self):
        recent = {"https://example.com/foo": "2026-09-19"}
        sections, stats = parse_sections(
            SAMPLE_MD, today="2026-09-23", recent_seen=recent, window_days=3,
        )
        assert stats["cross_day_drops"] == 0

    def test_today_excluded_from_recent(self):
        """Same-run safety: today's URL is NOT recent, so it's kept."""
        recent = {"https://example.com/foo": "2026-09-23"}
        sections, stats = parse_sections(
            SAMPLE_MD, today="2026-09-23", recent_seen=recent,
        )
        assert stats["cross_day_drops"] == 0
        kept_urls = [a["url"] for s in sections for a in s["articles"]]
        assert "https://example.com/foo" in kept_urls

    def test_canonical_matching_for_trailing_slash(self):
        """The 2026-09-23 regression: seen_urls.json had raw-with-/ keys; the
        parser must canonicalize the query side too so lookup hits."""
        # recent_seen was loaded from json with RAW keys (with trailing /)
        recent = {"https://example.com/foo/": "2026-09-22"}
        sections, stats = parse_sections(
            SAMPLE_MD, today="2026-09-23", recent_seen=recent,
        )
        assert stats["cross_day_drops"] == 1, (
            "Parser should canonicalize URL on lookup side too — "
            "raw key 'https://example.com/foo/' must hit canonical 'https://example.com/foo'."
        )


class TestCrossJobDedup:
    """Hard dedup across jobs (one URL → one article max per rollup)."""

    def test_hard_dedup_second_drop(self):
        cross_job = {"https://example.com/foo"}
        sections, stats = parse_sections(
            SAMPLE_MD, today="2026-09-23", cross_job_seen=cross_job,
        )
        # Foo was already kept by an earlier job → second occurrence dropped
        assert stats["cross_job_drops"] == 1
        kept_urls = [a["url"] for s in sections for a in s["articles"]]
        assert "https://example.com/foo" not in kept_urls
        assert "https://example.com/bar" in kept_urls
        assert "https://example.com/baz" in kept_urls


class TestTemplatePlaceholders:
    """A cron LLM that didn't finish a section leaves {URL} placeholders.

    These must NEVER enter the cross-day state (would block real URLs later)."""

    def test_template_only_no_url_is_dropped(self):
        md = """## 🛠️ 开发实践

**[1] Placeholder Article**
原文：{URL}

假模板的正文,会被前面的子代理后期替换
"""
        sections, _ = parse_sections(md, today="2026-09-23")
        # No real URL → article is dropped silently (no canonical URL to dedup)
        assert sections[0]["articles"] == []

    def test_template_partial_url_with_braces_dropped(self):
        md = """## 🛠️

**[1] Half**
原文：https://example.com/{slug}

正文
"""
        sections, _ = parse_sections(md, today="2026-09-23")
        # URL has { } → no match for http(s)://chars → dropped
        assert sections[0]["articles"] == []


class TestCleanBody:
    def test_bold_to_strong(self):
        assert "<strong>foo</strong>" in clean_body("**foo**")

    def test_italic_to_em(self):
        assert "<em>foo</em>" in clean_body("*foo*")

    def test_inline_code(self):
        assert "<code>foo</code>" in clean_body("`foo`")

    def test_markdown_link_to_text(self):
        # [text](url) → just text
        assert clean_body("[click](https://example.com)") == "click"

    def test_bullet_to_unicode(self):
        assert clean_body("- item") == "• item"
        assert clean_body("* item") == "• item"
