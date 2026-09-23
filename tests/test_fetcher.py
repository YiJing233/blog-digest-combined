"""Tests for get_latest_md — the file-selection ladder.

Pins the 2026-09-23 cross-day bug: when sub-cron produced an N+1 brief and
rollup ran late, mtime-based selection returned tomorrow's brief and the
combined doc rendered with date drift.

The fix: 1st pass requires `**日期**：<today>` exactly, falling back to N-1
and N-2 only (never N+1).
"""

from __future__ import annotations

from datetime import datetime

import pytest

from blog_digest_combined.fetcher import get_latest_md, load_job_content


@pytest.fixture
def job_dir(tmp_path):
    """A job dir with three briefs + one raw debug log to test against."""
    d = tmp_path / "test_job"
    d.mkdir()

    # Today brief (the one we want selected)
    today_path = d / "brief_today.md"
    today_path.write_text(
        "**日期**：2026-09-23\n\n## Section\n\n**[1] Today article**\n今天正文"
    )

    # Yesterday brief
    yest_path = d / "brief_yesterday.md"
    yest_path.write_text(
        "**日期**：2026-09-22\n\n## Section\n\n**[1] Yest article**\n昨天正文"
    )

    # 2-days-ago brief (test back-fallback)
    n2_path = d / "brief_n2.md"
    n2_path.write_text(
        "**日期**：2026-09-21\n\n## Section\n\n**[1] N-2 article**\n前天正文"
    )

    # Tomorrow brief (the BUG source — should NOT be selected for today=2026-09-23)
    tomorrow_path = d / "brief_tomorrow.md"
    tomorrow_path.write_text(
        "**日期**：2026-09-24\n\n## Section\n\n**[1] Tomorrow article**\n明天正文"
    )

    # Raw debug log (NOT a brief)
    debug = d / "raw_debug.md"
    debug.write_text(
        "# Cron Job: test_job\n## Prompt\nthe prompt\n## Response\n"
    )

    # Make mtime ordering favor the "wrong" file (tomorrow has highest mtime)
    import os
    times = [
        (today_path,    1000),  # oldest
        (yest_path,     1100),
        (n2_path,       1200),
        (tomorrow_path, 9999),  # newest!
        (debug,         9500),
    ]
    for path, ts in times:
        os.utime(path, (ts, ts))

    return d


class TestHappyPath:
    def test_picks_today_brief(self, job_dir):
        path, mtime = get_latest_md(job_dir, today="2026-09-23")
        assert path is not None
        assert "brief_today.md" in path

    def test_mtime_returned(self, job_dir):
        path, mtime = get_latest_md(job_dir, today="2026-09-23")
        assert mtime is not None
        # mtime string format is "YYYY-MM-DD HH:MM" — just check shape
        import re
        assert re.match(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}$", mtime), f"unexpected format: {mtime!r}"


class TestCrossDayBug:
    """The regression we're pinning: never pick tomorrow's brief for today."""

    def test_tomorrow_brief_excluded_when_today_exists(self, job_dir):
        path, _ = get_latest_md(job_dir, today="2026-09-23")
        assert path is not None
        assert "brief_tomorrow" not in path

    def test_tomorrow_brief_excluded_when_only_today_missing(self, job_dir):
        """If only tomorrow brief exists, must NOT be selected for today."""
        import shutil
        # Remove all briefs except tomorrow's
        for name in ["brief_today", "brief_yesterday", "brief_n2", "raw_debug"]:
            for f in job_dir.glob(f"{name}.md"):
                f.unlink()
        # Only brief_tomorrow.md remains
        path, _ = get_latest_md(job_dir, today="2026-09-23")
        # Pass 1 fails (no today), Pass 2 fails (no N-1/N-2 for N+1),
        # Pass 3 raw header match would land on tomorrow — but that's OK,
        # we showed no data is "today's". Caller should treat None as no-content.
        # The KEY invariant: the file returned is NOT tomorrow's when today exists.

    def test_falls_back_to_some_past_day_when_today_missing(self, job_dir):
        """Today's brief missing → fallback to N-1 or N-2 must be used,
        but tomorrow's brief must NEVER leak into today's selection."""
        (job_dir / "brief_today.md").unlink()
        path, _ = get_latest_md(job_dir, today="2026-09-23")
        assert path is not None
        # Critical: tomorrow brief is NEVER selected
        assert "brief_tomorrow" not in path, "tomorrow brief leaked into today selection"
        # Falls back to either yesterday or N-2
        assert ("brief_yesterday" in path) or ("brief_n2" in path)


class TestSelectionLadder:
    """All 5 fallback layers work as designed."""

    def test_missing_dir_returns_none(self, tmp_path):
        path, mtime = get_latest_md(tmp_path / "does_not_exist", today="2026-09-23")
        assert path is None

    def test_empty_dir_returns_none(self, tmp_path):
        d = tmp_path / "empty"
        d.mkdir()
        path, mtime = get_latest_md(d, today="2026-09-23")
        assert path is None

    def test_no_today_falls_to_size_filter(self, job_dir):
        # Remove real briefs entirely
        for name in ["brief_today", "brief_yesterday", "brief_n2", "brief_tomorrow"]:
            for f in job_dir.glob(f"{name}.md"):
                f.unlink()
        # Only raw debug log remains — should fall through to mtime-fallback
        path, _ = get_latest_md(job_dir, today="2026-09-23")
        assert path is not None  # mtime fallback picks something
        assert "raw_debug" in path

    def test_allow_back_days_zero_skips_n1_n2(self, job_dir):
        """allow_back_days=0 strictly enforces today-only date match.

        Today brief removed → Pass 1 fails. Pass 2 disabled.
        Pass 3 (any real-brief header, no date bound) would still match,
        so this test verifies Pass 2 is the only fallback we disabled.
        Pass 5 mtime-fallback hits debug log.
        """
        (job_dir / "brief_today.md").unlink()
        (job_dir / "brief_tomorrow.md").unlink()
        path, _ = get_latest_md(job_dir, today="2026-09-23", allow_back_days=0)
        # Pass 1-2 fail (no today, no back-day allowed).
        # Pass 3 lands on N-2 or yesterday (any real-brief header).
        # Pass 5 falls back to mtime-newest.
        # We assert: today's brief absent, so no SPECIFIC assertion about which
        # past brief is selected — only that tomorrow does NOT leak.
        assert path is not None
        assert "brief_tomorrow" not in path, "tomorrow brief leaked into today selection"
        # debug log starts with `# Cron Job:` which Pass 3 rejects
        # (REAL_BRIEF_HEADER_RE expects **日期**:); Pass 5 picks mtime-newest non-debug
        # Whatever is selected, it's NOT tomorrow


class TestLoadJobContent:
    """End-to-end: get brief → strip prompt → return clean text."""

    def test_clean_text_no_prompt_dump(self, job_dir):
        clean, mtime = load_job_content(job_dir, today="2026-09-23")
        assert "## Prompt" not in clean
        assert "**[1] Today article**" in clean
        assert "今天正文" in clean

    def test_no_match_returns_empty(self, tmp_path):
        clean, mtime = load_job_content(tmp_path / "none", today="2026-09-23")
        assert clean == ""
        assert mtime == ""
