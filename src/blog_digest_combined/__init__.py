"""blog-digest-combined — Hermes RSS daily-digest rollup.

三层 dedup (skill: rss-digest-dedup-architecture):
  1. 源分桶 — 子 cron 互不重叠 blog_id 子集 (本仓库不覆盖,由 blogwatcher 子 cron 实现)
  2. URL canonical 化 — 抗 utm/fragment/末尾斜杠 小变体
  3. 跨日 seen_urls.json — DEDUP_WINDOW_DAYS 默认 3 天

公共 API:
  - canonical_url(url)
  - extract_clean_content(raw_text)
  - parse_sections(text, recent_seen, today)
  - get_latest_md(job_dir, today)
  - load_seen_urls(path) / save_seen_urls(path, data)
  - is_url_in_recent_days(url, seen, today, window_days)
  - load_job_content(job_dir, today)
  - build_html(sources_data, today_str)
"""

__version__ = "0.1.0"
