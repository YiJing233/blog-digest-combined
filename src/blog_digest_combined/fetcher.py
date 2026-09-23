"""Pick the right .md for a given cron job, with today-bounded selection.

The bug this module exists to fix (2026-09-23):
  When the rollup cron (04:52) runs after the sub-cron (02-03:50) has produced
  NEXT-day output (rare but observed during retries/rate-limit), `get_latest_md`
  used to return whatever had the latest mtime — which could be tomorrow's
  brief. This caused "content truncated" symptoms (date drift between
  filename and content).

The fix: first pass requires the file's `**日期**：YYYY-MM-DD` header to
match `today` exactly. Fallback ladder allows N-1 and N-2 (sub-cron may
have run late, but never N+1).
"""

from __future__ import annotations

import glob
import os
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Optional

from .extractor import (
    DATE_HEADER_RE,
    MAX_REAL_BRIEF_BYTES,
    RAW_DEBUG_HINT_RE,
    REAL_BRIEF_HEADER_RE,
    extract_clean_content,
)


def get_latest_md(
    job_dir: Path | str,
    today: Optional[str] = None,
    allow_back_days: int = 2,
) -> tuple[Optional[str], Optional[str]]:
    """Return (relative-path, mtime-string) for today's brief — or None.

    Selection ladder (most-specific first):
      0. (Sub-cron special)  If today is set AND path is named {today}.md, return it
      1.                   today=YYYY-MM-DD header is exactly `today`
      2.                   today-1 or today-2 (sub-cron late)
      3.                   Any real-brief header (no today bound — debug)
      4.                   size < 50KB AND no `## Prompt` (legacy brief)
      5.                   mtime-fallback (any file)

    Args:
      allow_back_days: how many days back from today to accept as the brief.
                       Set to 0 to disallow N-1/N-2 fallback.
    """
    job_dir = Path(job_dir)
    if not job_dir.is_dir():
        return None, None

    md_files = glob.glob(str(job_dir / "*.md"))
    if not md_files:
        return None, None

    md_files.sort(key=os.path.getmtime, reverse=True)

    # Pass 0: {today}.md exact-match (HF papers convention)
    if today:
        today_file = job_dir / f"{today}.md"
        if today_file.exists():
            return _format(str(today_file))

    # Pass 1: today's date header
    if today:
        match = _scan(md_files, DATE_HEADER_RE, today)
        if match:
            return _format(match)

    # Pass 2: back-day fallback (sub-cron late)
    if today and allow_back_days > 0:
        try:
            today_d = datetime.strptime(today, "%Y-%m-%d").date()
        except ValueError:
            today_d = None
        if today_d:
            allow_dates = {
                (today_d - timedelta(days=d)).isoformat()
                for d in range(1, allow_back_days + 1)
            }
            for f in md_files:
                first_line = _peek_first_line(f)
                if not first_line:
                    continue
                m = DATE_HEADER_RE.match(first_line)
                if m and m.group(1) in allow_dates:
                    print(
                        f"[INFO] get_latest_md({job_dir.name}): today={today} → back-day fallback to {m.group(1)}",
                        file=sys.stderr,
                    )
                    return _format(f)

    # Pass 3: any real-brief header (today not specified)
    for f in md_files:
        first_line = _peek_first_line(f)
        if not first_line:
            continue
        if os.path.getsize(f) >= MAX_REAL_BRIEF_BYTES:
            continue
        if REAL_BRIEF_HEADER_RE.match(first_line):
            return _format(f)

    # Pass 4: size+no-debug
    for f in md_files:
        if os.path.getsize(f) >= MAX_REAL_BRIEF_BYTES:
            continue
        try:
            with open(f, encoding="utf-8", errors="replace") as fh:
                head = fh.read(2048)
            if RAW_DEBUG_HINT_RE.search(head):
                continue
            return _format(f)
        except OSError:
            continue

    # Pass 5: mtime-fallback
    return _format(md_files[0])


def _format(path: Optional[str]) -> tuple[Optional[str], Optional[str]]:
    if path is None:
        return None, None
    mtime_str = datetime.fromtimestamp(os.path.getmtime(path)).strftime("%Y-%m-%d %H:%M")
    return path, mtime_str


def _peek_first_line(path: str) -> Optional[str]:
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            return fh.readline().strip()
    except OSError:
        return None


def _scan(md_files: list[str], pattern, target_value: str) -> Optional[str]:
    for f in md_files:
        first_line = _peek_first_line(f)
        if not first_line:
            continue
        if os.path.getsize(f) >= MAX_REAL_BRIEF_BYTES:
            continue
        m = pattern.match(first_line)
        if m:
            captured = m.group(1) if m.groups() else m.group(0)
            if captured == target_value:
                return f
    return None


def load_job_content(
    job_dir: Path | str,
    today: Optional[str] = None,
) -> tuple[str, str]:
    """Pick the right brief for `today`, then strip prompt headers.

    Returns (clean_text, mtime_str).
    """
    path, mtime = get_latest_md(job_dir, today=today)
    if not path:
        return "", ""
    with open(path, encoding="utf-8") as f:
        raw = f.read()
    return extract_clean_content(raw), mtime
