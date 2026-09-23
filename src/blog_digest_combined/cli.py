"""CLI entry point — backward compatible with the original blog_digest_combined.py.

Reads from the same default job directories as the Hermes cron setup. Supports
``--today`` override for backfilling historical dates (testing, archival).
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import date as _date_cls
from pathlib import Path

from .dedup import (
    canonical_url,
    evict_old_entries,
    load_seen_urls,
    save_seen_urls,
)
from .extractor import extract_clean_content
from .fetcher import get_latest_md, load_job_content
from .parser import parse_sections
from .renderer import render_html, render_markdown


# ── Default job table (Hermes cron layout) ─────────────────────

DEFAULT_OUTPUT_BASE = Path(os.environ.get("HERMES_CRON_OUTPUT") or Path.home() / ".hermes" / "cron" / "output")

JOBS = {
    "iCloud 订阅":  "ae7df3150e0e",
    "Indie 科技":  "909cbd821c57",
    "ML 博主":     "8836652e22cb",
    "HF 论文":     "hf_papers_watcher",
}

JOB_DIR_OVERRIDES = {
    "hf_papers_watcher": DEFAULT_OUTPUT_BASE / "hf_papers_watcher",
}

DEDUP_WINDOW_DAYS = int(os.environ.get("DEDUP_WINDOW_DAYS", "3"))


def build_sources_data(today: str) -> tuple[list[dict], list[str], list[str], set[str]]:
    """Walk all configured jobs, run parse_sections, return aggregated data.

    Returns:
      sources_data: list suitable for render_html / render_markdown
      failed_jobs:  jobs whose content extraction returned empty
      empty_jobs:   jobs that parsed but produced 0 articles (after dedup)
      today_canonical_urls: all canonical URLs we're keeping today
                             (caller writes them to seen_urls.json AFTER successful render)
    """
    recent_seen = load_seen_urls(DEFAULT_OUTPUT_BASE / "combined" / "seen_urls.json")
    recent_seen, evicted = evict_old_entries(recent_seen, today, DEDUP_WINDOW_DAYS)
    if evicted:
        print(f"[INFO] Evicted {evicted} URLs older than {today} (window={DEDUP_WINDOW_DAYS}d)")
    print(f"[INFO] Cross-day dedup state: {len(recent_seen)} URLs in last {DEDUP_WINDOW_DAYS}d")

    sources_data = []
    failed_jobs = []
    empty_jobs = []
    cross_job_seen: set[str] = set()
    today_canonical_urls: set[str] = set()

    for label, job_id in JOBS.items():
        job_dir = JOB_DIR_OVERRIDES.get(job_id) or (DEFAULT_OUTPUT_BASE / job_id)
        content, mtime = load_job_content(job_dir, today=today)
        if not content:
            failed_jobs.append(label)
            print(f"[WARN] {label} ({job_id}): empty content")
            sources_data.append({
                "label": label, "job_id": job_id, "mtime": mtime,
                "content": content, "sections": [],
            })
            continue

        print(f"[INFO] {label} ({job_id}): {len(content)} chars clean, mtime={mtime}")
        sections, stats = parse_sections(
            content, today=today, recent_seen=recent_seen,
            cross_job_seen=cross_job_seen, window_days=DEDUP_WINDOW_DAYS,
        )
        n_articles = sum(len(s["articles"]) for s in sections)
        if stats["cross_day_drops"]:
            print(f"[DEDUP] {label}: dropped {stats['cross_day_drops']} cross-day duplicate(s)")
        if stats["cross_job_drops"]:
            print(f"[DEDUP] {label}: dropped {stats['cross_job_drops']} cross-job duplicate(s)")
        print(f"[INFO]   → {len(sections)} sections, {n_articles} articles")
        if n_articles == 0:
            empty_jobs.append(label)
        for sec in sections:
            for art in sec["articles"]:
                if art.get("url") and art["url"] != "#":
                    today_canonical_urls.add(canonical_url(art["url"]))
        sources_data.append({
            "label": label, "job_id": job_id, "mtime": mtime,
            "content": content, "sections": sections,
        })

    return sources_data, failed_jobs, empty_jobs, today_canonical_urls


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Hermes RSS daily-digest rollup")
    parser.add_argument("--today", help="Override today's date (YYYY-MM-DD) for backfill/test")
    parser.add_argument("--output-dir", help="Override output base dir (default: ~/.hermes/cron/output)")
    args = parser.parse_args(argv)

    global DEFAULT_OUTPUT_BASE
    if args.output_dir:
        DEFAULT_OUTPUT_BASE = Path(args.output_dir)

    today = args.today or _date_cls.today().strftime("%Y-%m-%d")
    sources_data, failed_jobs, empty_jobs, today_canonical_urls = build_sources_data(today)

    if failed_jobs:
        print(f"[WARN] Failed jobs: {', '.join(failed_jobs)}")
    if empty_jobs:
        print(f"[WARN] Empty jobs (after dedup): {', '.join(empty_jobs)}")

    total_articles = sum(
        len(art)
        for src in sources_data
        for sec in src.get("sections", [])
        for art in [sec["articles"]]
    )
    if total_articles == 0:
        print("[ERROR] No articles from any job. Aborting.")
        return 2

    combined_dir = DEFAULT_OUTPUT_BASE / "combined"
    combined_dir.mkdir(parents=True, exist_ok=True)
    md_path = combined_dir / f"blog_digest_{today}.md"
    html_path = combined_dir / f"blog_digest_{today}.html"
    md_path.write_text(render_markdown(sources_data, today), encoding="utf-8")
    html_path.write_text(render_html(sources_data, today), encoding="utf-8")
    print(f"[INFO] Written: {html_path}")
    print(f"[INFO] Written MD: {md_path}")

    # Atomic latest symlink
    latest = combined_dir / "blog_digest_latest.html"
    if latest.is_symlink() or latest.exists():
        latest.unlink()
    try:
        latest.symlink_to(html_path.name)
    except OSError:
        import shutil; shutil.copy2(html_path, latest)
    print(f"[INFO] Latest → {html_path.name}")

    print(
        f"[DONE] {today} · "
        f"{sum(len(s.get('sections', [])) for s in sources_data)} sections · "
        f"{total_articles} articles"
    )

    # Persist today's URLs into seen_urls.json (canonical keys!)
    if DEDUP_WINDOW_DAYS and today_canonical_urls:
        seen_path = combined_dir / "seen_urls.json"
        existing = load_seen_urls(seen_path)
        for u in today_canonical_urls:
            existing[u] = today
        save_seen_urls(seen_path, existing)
        print(f"[INFO] Updated seen_urls.json: +{len(today_canonical_urls)} URLs (total={len(existing)})")

    return 0


if __name__ == "__main__":
    sys.exit(main())
