# blog-digest-combined

> Hermes RSS daily-digest rollup — multi-source dedup + Kami-style HTML rendering

[![CI](https://github.com/yijing9718/blog-digest-combined/actions/workflows/ci.yml/badge.svg)](https://github.com/yijing9718/blog-digest-combined/actions/workflows/ci.yml)
[![codecov](https://codecov.io/gh/yijing9718/blog-digest-combined/graph/badge.svg)](https://codecov.io/gh/yijing9718/blog-digest-combined)

Hermes 是作者的[个人 AI agent 网关](https://github.com/yijing9718/hermes-agent),每天跑 4 个 RSS 摘要子 cron (iCloud 订阅 / Indie 科技 / ML 博主 / HF 论文)。
本仓库是日报汇总 rollup — 把这 4 个子 cron 的输出合并成一份 Kami 风格的 HTML/MD 文档,通过去重避免重复推送。

## 安装

```bash
pip install -e ".[dev]"
```

需要 Python 3.9+。无运行时依赖 (只用标准库)。

## 用法

```bash
# 默认: 读 ~/.hermes/cron/output/ 4 个子 cron 的当天输出
blog-digest-combined

# 回填特定日期 (测试用)
blog-digest-combined --today 2026-09-22

# 自定义输出根目录
blog-digest-combined --output-dir /tmp/hermes-test
```

输出文件:
- `~/.hermes/cron/output/combined/blog_digest_YYYY-MM-DD.md`
- `~/.hermes/cron/output/combined/blog_digest_YYYY-MM-DD.html`
- `~/.hermes/cron/output/combined/blog_digest_latest.html` (symlink)
- `~/.hermes/cron/output/combined/seen_urls.json` (跨日去重 state)

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
3. **抓变体**: utm/ref/source 参数、fragment、末尾斜杠 全部剥除

### `is_url_in_recent_days` 行为

- 命中窗口 = `[today - window_days, today - 1]`,**今天本身不算"近期"**(避免杀掉本次跑刚写入的 URL)
- `seen` 字典的 key **必须 canonical**: 历史 raw-URL key 也能命中(向后兼容,但会写 INFO 提示)

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

## 测试

```bash
pytest                          # 跑 77 个测试
pytest --cov=blog_digest_combined --cov-fail-under=80
```

当前覆盖率 **90.66%**,覆盖核心 bug 行为:
- 重复文章 (raw URL 与 canonical URL 碰撞)
- 内容被截 (N+1 brief 漏入 N 的 rollup)
- 模板占位符 `{URL}` 不会污染 state

## 已知 Pitfalls

详见 `tests/test_*.py` 的 docstring — 每个 test 都是从一个真实 bug 反推出来的回归保护:

| 日期 | Bug | Pinned by test |
|------|-----|----------------|
| 2026-09-23 | seen_urls 写漏 (raw/canonical 不一致) | `test_canonical_matching_for_trailing_slash` |
| 2026-09-23 | get_latest_md 拿明天 brief | `test_tomorrow_brief_excluded_when_today_exists` |
| 2026-09-23 | 模板 `{URL}` 污染 state | `test_template_only_no_url_is_dropped` |
| 2026-09-23 | renderer 空 source badge | `test_html_escapes_dangerous_titles` |

## 与 Hermes cron 的集成

`~/.hermes/scripts/blog_digest_combined.py` 是 thin wrapper:

```python
#!/usr/bin/env python3
from blog_digest_combined.cli import main
import sys
sys.exit(main(sys.argv[1:]))
```

装本包 (`pip install -e ~/projects/blog-digest-combined`) 后,cron 不需要改任何东西。

## License

MIT
