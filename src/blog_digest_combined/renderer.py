"""Render parsed sections to Markdown + Kami-style HTML."""

from __future__ import annotations

import html
import re
from typing import Iterable

from .parser import clean_body  # noqa: F401  (re-exported for callers)


# ── Markdown renderer ───────────────────────────────────────────

def render_markdown(sources_data: list[dict], today_str: str) -> str:
    """Assemble per-source sections into one Markdown document."""
    total_articles = sum(
        len(art)
        for src in sources_data
        for sec in src.get("sections", [])
        for art in [sec["articles"]]
    )
    active_sources = sum(1 for s in sources_data if s.get("sections"))

    lines = [f"# 日报汇总 | {today_str}\n"]
    lines.append(
        f"共筛选自 {active_sources} 个来源 · {total_articles} 篇精选\n\n"
    )
    for src in sources_data:
        if not src.get("sections"):
            continue
        lines.append(f"## {src['label']}\n\n")
        for sec in src["sections"]:
            for art in sec["articles"]:
                url = art.get("url", "") or "#"
                if url == "#":
                    url_match = re.search(
                        r'https?://[^\s\)\]\"\'<>]+', art["body"],
                    )
                    url = url_match.group(0) if url_match else "#"
                lines.append(f"### [{art['title']}]({url})\n\n")
                body_plain = re.sub(r"<[^>]+>", "", art["body"])
                body_plain = re.sub(r"\n\n+", "\n\n", body_plain).strip()
                lines.append(body_plain + "\n\n")
    return "".join(lines)


# ── Kami-style HTML renderer ─────────────────────────────────────

KAMI_CSS = """
    :root {
      --canvas:     #f5f4ed;
      --ivory:      #faf9f5;
      --sand:       #e8e6dc;
      --ink:        #1b365d;
      --ink-light:  #2d5a8a;
      --near-black: #141413;
      --charcoal:   #4d4c48;
      --olive:      #5e5d59;
      --stone:      #87867f;
      --warm-s:     #b0aea5;
    }
    * { margin: 0; padding: 0; box-sizing: border-box; }
    body { font-family: 'Inter','Noto Serif SC',system-ui,sans-serif;
           background: var(--canvas); color: var(--near-black);
           font-size: 15px; line-height: 1.6; -webkit-font-smoothing: antialiased; }
    h1,h2,h3 { font-family: 'Newsreader','Noto Serif SC',Georgia,serif;
                font-weight: 500; letter-spacing: -0.01em; }
    a { color: var(--ink); text-decoration: none; }
    a:hover { text-decoration: underline; }
    .page { max-width: 740px; margin: 0 auto; padding: 80px 40px 120px; }
    .doc-header { padding-bottom: 40px; margin-bottom: 56px; border-bottom: 1px solid var(--sand); }
    .doc-label { font-size: 11px; font-weight: 600; letter-spacing: 0.12em;
                 text-transform: uppercase; color: var(--stone); margin-bottom: 14px; }
    .doc-title { font-size: 36px; font-weight: 500; line-height: 1.15;
                 color: var(--near-black); margin-bottom: 20px; letter-spacing: -0.02em; }
    .doc-meta  { font-size: 13px; color: var(--stone); margin-bottom: 8px; }
    .doc-desc  { font-size: 14px; color: var(--olive); }
    .sources { display: flex; gap: 8px; flex-wrap: wrap; margin-top: 12px; }
    .source-badge { font-size: 11px; font-weight: 500; padding: 3px 10px;
                    border-radius: 20px; background: var(--sand); color: var(--charcoal); }
    .section { margin-bottom: 64px; }
    .section-header { display: flex; align-items: center; gap: 16px; margin-bottom: 28px; }
    .section-title { font-size: 18px; font-weight: 500; color: var(--near-black); }
    .section-rule { flex: 1; height: 1px; background: var(--sand); }
    .article { background: var(--ivory); border-radius: 4px; margin-bottom: 16px;
                box-shadow: 0 0 0 1px rgba(20,20,19,0.07), 0 1px 2px rgba(20,20,19,0.05); }
    .article-inner { display: flex; }
    .article-accent { width: 3px; background: var(--ink); border-radius: 4px 0 0 4px; flex-shrink: 0; }
    .article-body { padding: 20px 24px; flex: 1; }
    .article-title { font-size: 15px; font-weight: 500; color: var(--near-black);
                     margin-bottom: 8px; line-height: 1.4; }
    .article-title a { color: inherit; }
    .article-title a:hover { color: var(--ink-light); }
    .article-body-text { font-size: 14px; color: var(--charcoal); line-height: 1.65; }
    .article-body-text p { margin-bottom: 8px; }
    .article-body-text p:last-child { margin-bottom: 0; }
    .article-body-text .source-link { display: inline-block; margin-top: 8px; font-size: 12px;
                                       color: var(--ink); }
    .section-count { font-size: 11px; color: var(--warm-s); font-weight: 500; margin-left: auto; }
    .footer { margin-top: 80px; padding-top: 32px; border-top: 1px solid var(--sand);
              font-size: 12px; color: var(--warm-s); display: flex; justify-content: space-between; }
"""


_ARTICLE_HTML = """<div class="article">
  <div class="article-inner">
    <div class="article-accent"></div>
    <div class="article-body">
      <div class="article-title"><a href="{url}" target="_blank">{title}</a></div>
      <div class="article-body-text">{body}</div>
    </div>
  </div>
</div>"""


def _article_body_html(art: dict) -> str:
    """Convert article body to HTML, skipping 原文 line + trailing ---."""
    url = art.get("url", "") or "#"
    body_lines = []
    in_source = False
    for line in art["body"].split("\n"):
        if re.match(r"^原文：https?://", line):
            in_source = False
            continue
        if in_source:
            continue
        if line.strip() in ("---", "****"):
            in_source = True
            continue
        if line.strip():
            body_lines.append(f"<p>{line}</p>")
    body = "\n".join(body_lines)
    body += f'<div class="source-link">🔗 <a href="{html.escape(url)}" target="_blank">原文链接</a></div>'
    return body


def render_article(art: dict) -> str:
    title = html.escape(art["title"])
    url = art.get("url", "") or "#"
    if not url or url == "#":
        url_match = re.search(r'https?://[^\s\)\]\"\'<>]+', art["body"])
        url = url_match.group(0) if url_match else "#"
    body = _article_body_html(art)
    return _ARTICLE_HTML.format(title=title, body=body, url=url)


def render_html(sources_data: list[dict], today_str: str) -> str:
    sections_html = ""
    total_articles = 0
    for src in sources_data:
        if not src.get("sections"):
            continue
        sections_html += '<div class="section">'
        sections_html += '  <div class="section-header">'
        sections_html += f'    <div class="section-title">{html.escape(src["label"])}</div>'
        sec_count = sum(len(s["articles"]) for s in src["sections"])
        total_articles += sec_count
        sections_html += f'    <div class="section-count">{sec_count} 篇</div>'
        sections_html += '    <div class="section-rule"></div>'
        sections_html += '  </div>'
        for sec in src["sections"]:
            for art in sec["articles"]:
                sections_html += render_article(art)
        sections_html += "</div>"

    badges = "".join(
        f'<span class="source-badge">{html.escape(s["label"])}</span>'
        for s in sources_data if s.get("sections")
    )
    active_sources = sum(1 for s in sources_data if s.get("sections"))

    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>日报汇总 | {today_str}</title>
  <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600&family=Newsreader:ital,wght@0,400;0,500;1,400&family=Noto+Serif+SC:wght@500&family=JetBrains+Mono&display=swap" rel="stylesheet">
  <style>{KAMI_CSS}</style>
</head>
<body>
  <div class="page">
    <header class="doc-header">
      <div class="doc-label">Daily Digest</div>
      <h1 class="doc-title">日报汇总</h1>
      <div class="doc-meta">{today_str} · {total_articles} 篇精选</div>
      <div class="doc-desc">共筛选自 <span>{active_sources} 个来源</span></div>
      <div class="sources">{badges}</div>
    </header>
    <main>{sections_html}</main>
    <footer class="footer">
      <span>Generated by Hermes · Kami Design</span>
      <span>{today_str}</span>
    </footer>
  </div>
</body>
</html>"""
