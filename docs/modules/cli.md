# `cli` module

> Entry point. Wires all other modules together.

Source: `src/blog_digest_combined/cli.py` (170 lines).

## Why a thin entry point

This module does almost no logic — it's glue code that:
1. Iterates the `JOBS` table
2. Calls `load_job_content` (which calls `get_latest_md` + `extract_clean_content`)
3. Calls `parse_sections` per job
4. Aggregates everything into `sources_data`
5. Calls `render_html` / `render_markdown`
6. Writes output files + updates `seen_urls.json`

If you find yourself adding business logic here, push it down into one of
the leaf modules. `cli.py` is the place for:
- Default configuration (job table, output paths)
- Argument parsing
- Output file writing
- Exit code mapping

## Public API

### `main(argv=None) -> int`

The cron entry point. Called by `blog_digest_combined_wrapper.py` from
`~/.hermes/scripts/`.

**Args** (CLI):
- `--today YYYY-MM-DD` — override the rollup's date (backfill/test)
- `--output-dir PATH` — override `~/.hermes/cron/output/`

**Exit codes**:
| Code | Meaning |
|------|---------|
| 0 | Success — at least one article kept, output written |
| 2 | All jobs failed OR all articles dedup'd to zero |

**Side effects**:
- Writes `combined/blog_digest_YYYY-MM-DD.{md,html}`
- Updates (atomic) `combined/blog_digest_latest.html` symlink
- Updates (atomic) `combined/seen_urls.json`

### `build_sources_data(today) -> (sources_data, failed_jobs, empty_jobs, today_canonical_urls)`

Per-job iteration. Returns the structured data for `render_*` calls.

`sources_data` shape:
```python
[
  {
    "label":   "iCloud 订阅",
    "job_id":  "ae7df3150e0e",
    "mtime":   "2026-09-23 03:57",
    "content": "...",       # raw cleaned content (after extract_clean_content)
    "sections": [...]      # parsed sections (from parse_sections)
  },
  ...
]
```

`failed_jobs`: job labels whose `load_job_content` returned empty.

`empty_jobs`: job labels whose content parsed to zero articles after dedup.

`today_canonical_urls`: set of canonical URLs the rollup is shipping today.
The caller writes these to `seen_urls.json` AFTER successful render.

## Constants

### `JOBS`

The sub-cron job table:
```python
JOBS = {
    "iCloud 订阅": "ae7df3150e0e",
    "Indie 科技":  "909cbd821c57",
    "ML 博主":     "8836652e22cb",
    "HF 论文":     "hf_papers_watcher",
}
```

To add a new source: see [`docs/recipes/add-new-source.md`](../recipes/add-new-source.md).

### `JOB_DIR_OVERRIDES`

Per-job path overrides (rare). Currently only used for `hf_papers_watcher`
which uses a non-standard dir name.

```python
JOB_DIR_OVERRIDES = {
    "hf_papers_watcher": DEFAULT_OUTPUT_BASE / "hf_papers_watcher",
}
```

**Documented limitation**: `JOB_DIR_OVERRIDES` is frozen at import time
(see `TestJobDirOverrides::test_resolved_path_under_default_base`). When
the CLI is invoked with `--output-dir`, this dict doesn't reflect the new
base. This is OK because:
- `build_sources_data` resolves paths via `JOB_DIR_OVERRIDES.get(job_id) or DEFAULT_OUTPUT_BASE / job_id`
- The override dict is only relevant when `job_id` collides with a real path

### `DEFAULT_OUTPUT_BASE`

`Path(os.environ.get("HERMES_CRON_OUTPUT") or Path.home() / ".hermes" / "cron" / "output")`

Override priority:
1. `--output-dir` CLI flag (highest)
2. `HERMES_CRON_OUTPUT` env var
3. `~/.hermes/cron/output/` (default)

### `DEDUP_WINDOW_DAYS`

`int(os.environ.get("DEDUP_WINDOW_DAYS", "3"))`

The cross-day dedup window. URL remembered for N days, then evicted.

**Why 3 days?** Cron fires daily. 3 days means:
- Day 1: ship article, write to seen_urls
- Day 2: dedup against yesterday's seen
- Day 3: dedup against day-before-yesterday's seen
- Day 4: evicted from window — would re-ship

If your sub-cron produces the same article every few days (e.g. recurring
newsletter issues), bump to 7 days. If your sub-crons produce all-unique
content, drop to 0 to disable dedup entirely.

## Cron integration

`~/.hermes/cron/combined_feishu.sh` calls:

```bash
cd ~/.hermes/cron/output/combined
python3 /home/yiking/.hermes/scripts/blog_digest_combined_wrapper.py
```

`blog_digest_combined_wrapper.py` is a 5-line shim:
```python
import sys
from blog_digest_combined.cli import main
sys.exit(main(sys.argv[1:]))
```

The wrapper's name avoids shadowing — see
[`docs/troubleshooting.md#name-collision-with-pip-package`](../troubleshooting.md).

## Performance budget

| Phase | Cost |
|-------|------|
| `load_job_content` × 4 | ~40ms |
| `parse_sections` × 4 | ~50ms |
| `render_html` / `render_markdown` | ~30ms |
| `save_seen_urls` | ~10ms |
| **Total** | **~130ms** |

Well under the 60s cron deadline.

## What's NOT in this module

- Configuration parsing — keep simple CLI flags, no config files
- Email/notification delivery — that's `combined_feishu.sh`'s job
- Retry logic — cron runtime handles retries
- Logging beyond stderr prints — operator reads cron logs directly