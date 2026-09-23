# blog-digest-combined

> Hermes RSS daily-digest rollup — multi-source dedup + Kami-style HTML rendering

[![CI](https://github.com/YiJing233/blog-digest-combined/actions/workflows/ci.yml/badge.svg)](https://github.com/YiJing233/blog-digest-combined/actions/workflows/ci.yml)
[![codecov](https://codecov.io/gh/YiJing233/blog-digest-combined/graph/badge.svg)](https://codecov.io/gh/YiJing233/blog-digest-combined)
[![tests](https://img.shields.io/badge/tests-170%20passed-brightgreen)](tests/)
[![coverage](https://img.shields.io/badge/coverage-91.82%25-brightgreen)](tests/)

Hermes 是作者的[个人 AI agent 网关](https://github.com/YiJing233/hermes-agent),每天跑 4 个 RSS 摘要子 cron (iCloud 订阅 / Indie 科技 / ML 博主 / HF 论文)。
本仓库是日报汇总 rollup — 把这 4 个子 cron 的输出合并成一份 Kami 风格的 HTML/MD 文档,通过去重避免重复推送。

## 5 分钟上手

```bash
# 安装 (开发模式 — 改源码立刻生效)
cd ~/projects/blog-digest-combined
pip install -e .

# 默认: 读 ~/.hermes/cron/output/ 4 个子 cron 的当天输出
blog-digest-combined

# 回填特定日期 (测试用)
blog-digest-combined --today 2026-09-22

# 自定义输出根目录
blog-digest-combined --output-dir /tmp/hermes-test
```

需要 Python 3.9+。无运行时依赖 (只用标准库)。

## 文档导航

| 你想知道… | 读这个 |
|----------|---------|
| 这个项目是怎么工作的 | [docs/architecture.md](docs/architecture.md) |
| 某个具体函数的契约 / API | [docs/reference/api.md](docs/reference/api.md) 或 [docs/modules/](docs/modules/) |
| 怎么加一个新 sub-cron 来源 | [docs/recipes/add-new-source.md](docs/recipes/add-new-source.md) |
| `seen_urls.json` 怎么清理 / 迁移 | [docs/recipes/backfill-dedup.md](docs/recipes/backfill-dedup.md) |
| 文章重复/缺失怎么调试 | [docs/recipes/debug-why-article-shipped.md](docs/recipes/debug-why-article-shipped.md) |
| 改代码后怎么验证没破 | [docs/recipes/run-end-to-end-test.md](docs/recipes/run-end-to-end-test.md) |
| 常见失败 + 诊断 | [docs/troubleshooting.md](docs/troubleshooting.md) |
| 改了 docstring / 想要代码示例 | [docs/reference/api.md](docs/reference/api.md) |

## 输出文件

每次 `main()` 调用产生:

| 文件 | 内容 |
|------|------|
| `combined/blog_digest_YYYY-MM-DD.md` | Markdown 源 — Feishu/Telegram 推送用 |
| `combined/blog_digest_YYYY-MM-DD.html` | Kami 样式 HTML — 可视化 |
| `combined/blog_digest_latest.html` | 软链接 → 今天 HTML |
| `combined/seen_urls.json` | 跨日去重 state |

## 模块拆解

```
src/blog_digest_combined/
├── __init__.py          — package metadata
├── dedup.py             — canonical_url + seen_urls.json 持久化
├── extractor.py         — extract_clean_content: 剥离 SKILL.md prompt dump
├── fetcher.py           — get_latest_md: today-bound 文件选择
├── parser.py            — parse_sections: MD → sections/articles
├── renderer.py          — render_markdown / render_html (Kami-style)
└── cli.py               — main() 入口 + JOBS 任务表
```

## 设计契约

### `canonical_url(u)` 必须满足

1. **幂等**: `canonical_url(canonical_url(x)) == canonical_url(x)`
2. **纯函数**: 不抛异常,失败 fallback 原值
3. **抓变体**: utm_* / fbclid / gclid 参数、fragment、末尾斜杠、host case 全部归一

### `is_url_in_recent_days` 行为

- 命中窗口 = `[today - window_days, today - 1]`,**今天本身不算"近期"**(避免杀掉本次跑刚写入的 URL)
- `seen` 字典的 key **必须 canonical**: 历史 raw-URL key 也能命中(向后兼容,slow-path 兜底)

### `get_latest_md` 选择层级

| Pass | 匹配条件 | 用途 |
|------|--------|------|
| 0 | `{today}.md` exact-match | HF papers 命名约定 |
| 1 | 首行 `**日期**：<today>` | 严格今天 |
| 2 | 首行日期 = today-1 或 today-2 | 子 cron 延后 fallback |
| 3 | 任意 `**日期**：…` header | 老格式,无 today 边界 |
| 4 | `< 50KB` + 无 `## Prompt` | 兜底老 brief |
| 5 | mtime 最新 | 任何文件 |

**关键不变量: 第二天 brief (N+1) 永远不会被今天 (N) 的 rollup 选中**。

### `parse_sections` 行为

- URL 抽取:`URL_RE.search(body)` 取第一个 `https?://...`
- 模板占位符(URL 含 `{` 或 `}`)→ 静默丢弃,绝不污染 state
- 跨日 dedup 用 `recent_seen` dict(3 天窗口)
- 跨 job dedup 用 `cross_job_seen` set(本次 run 直接传,会被 in-place 修改)

## 测试

```bash
PYTHONPATH=src python3 -m pytest tests/ -v
PYTHONPATH=src python3 -m pytest tests/ --cov=blog_digest_combined --cov-fail-under=80
```

**170 tests passed, 91.82% coverage.**

涵盖的回归(bug → test):
| 日期 | Bug | Pinned by |
|------|-----|-----------|
| 2026-09-23 | seen_urls 写漏 (raw/canonical 不一致) | `test_canonical_matching_for_trailing_slash` |
| 2026-09-23 | get_latest_md 拿明天 brief | `test_tomorrow_brief_excluded_when_today_exists` |
| 2026-09-23 | 模板 `{URL}` 污染 state | `test_template_only_no_url_is_dropped` |
| 2026-09-23 | renderer 空 source badge | `test_html_escapes_dangerous_titles` |
| 2026-09-23 | XSS in body content (`<img onerror=...>`) | `test_no_inner_script_after_xss_in_title_and_body` |
| 2026-09-23 | XSS in URL (`javascript:`) | `test_no_inner_script_after_xss_in_title_and_body` |

完整列表见 [CHANGELOG.md](CHANGELOG.md) 的 [0.2.0] 段。

## 与 Hermes cron 的集成

`~/.hermes/scripts/blog_digest_combined.py` 被重命名为
`~/.hermes/scripts/blog_digest_combined_wrapper.py`(避免 shadow 安装的
同名 package),内容是 5 行 thin wrapper:

```python
#!/usr/bin/env python3
import sys
from blog_digest_combined.cli import main

if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
```

`~/.hermes/scripts/combined_feishu.sh` 调用从 `python3 blog_digest_combined.py`
改为 `python3 blog_digest_combined_wrapper.py`。无需改 cron 配置。

详见 [docs/troubleshooting.md § Case 8](docs/troubleshooting.md#case-8-wrapper-script-name-collision)。

## 开发流程

```bash
# 改完代码,跑测试:
PYTHONPATH=src python3 -m pytest tests/ -v

# 提交:
git add -A && git commit -m "..."

# 推 GitHub + CI 自动跑 3 个 Python 版本:
git push
```

新加一个 sub-cron? [docs/recipes/add-new-source.md](docs/recipes/add-new-source.md)
新加一个 tracking param? [docs/recipes/add-new-tracking-param.md](docs/recipes/add-new-tracking-param.md)

## License

MIT