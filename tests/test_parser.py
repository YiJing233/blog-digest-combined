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


class TestSectionBoundary:
    """Sections are bounded by `## title` lines.

    Pin that `### subheading` does NOT trigger section change (parser treats
    `## ` and `### ` as different headings — `### ` is content, `## ` is section)."""

    def test_articles_with_subsections_dont_split(self):
        """An article body can contain `### foo` (subheading) without
        creating a new section."""
        md = """**日期**：2026-09-23

## 🔬 技术深度

**[1] Article with internal subheadings**
原文：https://example.com/a

正文第一段.

### 子话题 1
详细内容.

### 子话题 2
更多内容.

---

**[2] Another article**
原文：https://example.com/b

Another content.
"""
        sections, _ = parse_sections(md, today="2026-09-23")
        assert len(sections) == 1
        assert len(sections[0]["articles"]) == 2
        art1 = sections[0]["articles"][0]
        assert "### 子话题 1" in art1["body"] or "子话题 1" in art1["body"]

    def test_consecutive_sections_no_blank_lines(self):
        """Sections separated by no blank lines."""
        md = """**日期**：2026-09-23
## 🔬 Section A
**[1] First**
原文：https://example.com/a
content A
## 🏢 Section B
**[2] Second**
原文：https://example.com/b
content B
"""
        sections, _ = parse_sections(md, today="2026-09-23")
        assert len(sections) == 2
        assert "Section A" in sections[0]["title"]
        assert "Section B" in sections[1]["title"]
        assert len(sections[0]["articles"]) == 1
        assert len(sections[1]["articles"]) == 1


class TestUrlExtractionVariants:
    """Pin all the URL extraction patterns we care about."""

    def test_url_in_markdown_link_format(self):
        md = """## Test

**[1] Article**
[here](https://example.com/foo)

content
"""
        sections, _ = parse_sections(md, today="2026-09-23")
        arts = [a for s in sections for a in s["articles"]]
        if arts:
            assert arts[0]["url"] == "https://example.com/foo"

    def test_url_inside_parentheses(self):
        md = """## Test

**[1] Article**
原文：(https://example.com/foo)

content
"""
        sections, _ = parse_sections(md, today="2026-09-23")
        arts = [a for s in sections for a in s["articles"]]
        if arts:
            assert "example.com/foo" in arts[0]["url"]

    def test_url_with_query_params(self):
        md = """## Test

**[1] A**
原文：https://example.com/foo?key=val&utm_source=t

c
"""
        sections, _ = parse_sections(md, today="2026-09-23")
        arts = [a for s in sections for a in s["articles"]]
        assert arts
        assert "key=val" in arts[0]["url"]


class TestUnicodeInTitlesAndSections:
    """CJK, brackets, emoji."""

    def test_title_with_chinese_brackets(self):
        md = """## Test

**【这是一篇中文文章】**
原文：https://example.com/foo

content
"""
        sections, _ = parse_sections(md, today="2026-09-23")
        arts = [a for s in sections for a in s["articles"]]
        if arts:
            assert "这是一篇中文文章" in arts[0]["title"]

    def test_section_with_emoji(self):
        md = """**日期**：2026-09-23

## 🚀 产业动态

**[1] a**
原文：https://x.com/a
c

---

## 🛠️ 开发实践

**[2] b**
原文：https://x.com/b
c
"""
        sections, _ = parse_sections(md, today="2026-09-23")
        assert len(sections) == 2
        assert "🚀 产业动态" in sections[0]["title"]
        assert "🛠️ 开发实践" in sections[1]["title"]


class TestEmptyAndEdgeInputs:
    """Document behavior on weird-but-real inputs."""

    def test_completely_empty(self):
        sections, stats = parse_sections("", today="2026-09-23")
        assert sections == []
        assert stats["kept"] == 0

    def test_only_header_no_articles(self):
        md = "**日期**：2026-09-23\n\n## Section with no articles\n"
        sections, _ = parse_sections(md, today="2026-09-23")
        assert sections == [] or all(len(s["articles"]) == 0 for s in sections)

    def test_article_without_url_dropped(self):
        md = """## Test

**[1] No URL article**
(no URL line)

content

---

**[2] With URL**
原文：https://example.com/foo

content
"""
        sections, _ = parse_sections(md, today="2026-09-23")
        arts = [a for s in sections for a in s["articles"]]
        titles = [a["title"] for a in arts]
        assert "No URL article" not in titles
        assert "With URL" in titles


class TestDedupCounters:
    """Pins the exact return shape of `parse_sections`."""

    def test_stats_keys_present(self):
        md = "## S\n**[1] a**\n原文：https://x.com/a\nc"
        sections, stats = parse_sections(md, today="2026-09-23")
        assert set(stats.keys()) == {"cross_day_drops", "cross_job_drops", "kept"}
        assert stats["kept"] == 1
        assert stats["cross_day_drops"] == 0
        assert stats["cross_job_drops"] == 0

    def test_stats_counters_accumulate(self):
        recent = {"https://x.com/a": "2026-09-22"}
        cross = {"https://x.com/b"}
        md = """## S
**[1] a (cross-day)**
原文：https://x.com/a
c
**[2] b (cross-job)**
原文：https://x.com/b
c
**[3] c (kept)**
原文：https://x.com/c
c
"""
        sections, stats = parse_sections(
            md, today="2026-09-23", recent_seen=recent, cross_job_seen=cross,
        )
        assert stats["cross_day_drops"] == 1
        assert stats["cross_job_drops"] == 1
        assert stats["kept"] == 1


class TestCrossJobDedupSetPassing:
    """The cross-job `seen_urls` set is mutable across calls."""

    def test_set_grows_across_calls_and_dedups_next_call(self):
        seen = set()
        first_md = """## S
**[1] a**
原文：https://example.com/foo
c
"""
        sections1, stats1 = parse_sections(first_md, today="2026-09-23", cross_job_seen=seen)
        assert stats1["kept"] == 1
        assert "https://example.com/foo" in seen

        second_md = """## S2
**[1] b**
原文：https://example.com/foo
c
"""
        sections2, stats2 = parse_sections(second_md, today="2026-09-23", cross_job_seen=seen)
        assert stats2["cross_job_drops"] == 1
        assert stats2["kept"] == 0


class TestCleanBodyEdgeCases:
    def test_preserves_paragraph_breaks(self):
        raw = "paragraph one\n\nparagraph two\n\nparagraph three"
        out = clean_body(raw)
        assert "\n\n" in out
        assert "paragraph one" in out
        assert "paragraph three" in out
