"""Markdown section + article parser.

A blogwatcher cron output looks like:

    **日期**：2026-09-23

    ## 🔬 技术深度

    **[1] Foo**
    原文：https://example.com/foo

    背景：...
    核心观点：...
    意义：...

    ---

    **[2] Bar**
    ...

parse_sections:
  - Splits by ## headings into sections
  - Each section contains articles  **[N] Title**  + body until next article/section
  - Cleans body via clean_body() — preserve newlines, normalize inline markdown
  - Two-level dedup:
      cross-job:    seen_urls  set (canonical URLs across jobs in one run)
      cross-day:    recent_seen dict {canonical: "YYYY-MM-DD"} (3-day window)
"""

from __future__ import annotations

import re
from typing import Optional

from .dedup import canonical_url, is_url_in_recent_days


ARTICLE_TITLE_RE = re.compile(r'^\*\*\[(\d+)\]\s*(.+?)\*\*\s*$')
SECTION_RE = re.compile(r'^##\s+(.+)$')
URL_RE = re.compile(r'https?://[^\s\)\]\"\'<>]+')

# Hard skip: prompt placeholder bodies (no real URL = definitely not a real article).
# Matches any URL containing ``{`` or ``}`` (template variable still in flight)
# OR any "URL" that is purely a placeholder token.
_TEMPLATE_PLACEHOLDER_RE = re.compile(r"[{}]")


def parse_sections(
    text: str,
    today: str,
    recent_seen: Optional[dict[str, str]] = None,
    cross_job_seen: Optional[set[str]] = None,
    window_days: int = 3,
) -> tuple[list[dict], dict]:
    """Parse markdown into sections. Apply two-level URL dedup.

    Returns: (sections, stats)
      sections = [{"title": str, "articles": [{"title", "num", "body", "url"}]}, ...]
      stats    = {"cross_day_drops": int, "cross_job_drops": int, "kept": int}
    """
    if recent_seen is None:
        recent_seen = {}
    if cross_job_seen is None:
        cross_job_seen = set()

    sections: list[dict] = []
    current = {"title": "", "articles": []}

    in_code_fence = False
    for line in text.split("\n"):
        stripped = line.strip()
        if stripped.startswith("```"):
            in_code_fence = not in_code_fence
            continue
        if in_code_fence:
            continue

        m_sec = SECTION_RE.match(line)
        if m_sec:
            title = m_sec.group(1).strip()
            if current["title"] or current["articles"]:
                sections.append(current)
            current = {"title": title, "articles": []}
            continue

        m_art = ARTICLE_TITLE_RE.match(line)
        if m_art:
            num = m_art.group(1)
            title = m_art.group(2).strip()
            current["articles"].append({
                "title": title, "num": num, "body": "", "url": "",
            })
            continue

        if current["articles"]:
            current["articles"][-1]["body"] += line + "\n"

    if current["title"] or current["articles"]:
        sections.append(current)

    # Apply dedup + body cleanup
    cross_day_drops = 0
    cross_job_drops = 0
    kept = 0

    for sec in sections:
        new_articles = []
        for art in sec["articles"]:
            url_match = URL_RE.search(art["body"])
            url = url_match.group(0) if url_match else ""

            if not url or _TEMPLATE_PLACEHOLDER_RE.search(url):
                continue

            canonical = canonical_url(url)

            # Cross-day: drop URLs we've already shown in the last N days
            if window_days and recent_seen and is_url_in_recent_days(
                canonical, recent_seen, today, window_days,
            ):
                cross_day_drops += 1
                continue

            # Cross-job: same canonical URL already kept by an earlier job this run
            if canonical in cross_job_seen:
                cross_job_drops += 1
                continue
            cross_job_seen.add(canonical)

            art["url"] = url
            art["body"] = clean_body(art["body"])
            new_articles.append(art)
            kept += 1
        sec["articles"] = new_articles

    stats = {
        "cross_day_drops": cross_day_drops,
        "cross_job_drops": cross_job_drops,
        "kept": kept,
    }
    return sections, stats


def clean_body(raw: str) -> str:
    """Strip residual markdown inline syntax; preserve paragraph breaks."""
    lines = []
    for line in raw.split("\n"):
        line = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', line)
        line = re.sub(r'\*(.+?)\*',     r'<em>\1</em>',       line)
        line = re.sub(r'`(.+?)`',       r'<code>\1</code>',  line)
        line = re.sub(r'\[([^\]]+)\]\([^\)]+\)', r'\1',       line)
        line = re.sub(r'^\s*[-*]\s+',   '• ',                 line)
        line = line.strip()
        lines.append(line)
    return "\n".join(lines).strip()
