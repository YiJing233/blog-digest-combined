# Recipe: Add a new sub-cron source

When a new RSS feed / newsletter / paper list needs to be in the daily digest.

## Overview

```
[New cron job]                    [Rollup]
   runs at 02:00         cron at 04:52
       │                         │
       ▼                         ▼
~/.hermes/cron/output/      blog_digest_combined
   <NEW_JOB_ID>/                  reads from JOBS
       │                         table
       ▼                         ▼
   brief.md             filtered + dedup'd
```

## Steps

### 1. Add the sub-cron first

Use `hermes cronjob create` (or whatever your cron creation tool is):

```bash
hermes cronjob create \
  --name "AAIF Weekly" \
  --schedule "0 9 * * 1" \
  --prompt "..." \
  --output-dir "$HOME/.hermes/cron/output/aaif_weekly"
```

**Note the output dir name** — that's what you'll use in step 2.

### 2. Confirm it produces output

Wait one cycle (or run it manually) and verify:

```bash
ls -la ~/.hermes/cron/output/aaif_weekly/
# Should see at least one .md file with **日期**: YYYY-MM-DD header
```

The output brief should look like:

```
**日期**：2026-09-23

## Topic

**[1] Article Title**
原文：https://example.com/foo

背景：...
核心观点：...
```

If the sub-cron produces different format (e.g. no `## sections`, no `**[N]` markers),
the rollup's `parser.py` won't extract articles correctly. Either:
- Update the sub-cron prompt to produce the expected format, OR
- Patch `parser.py` to handle the new shape (add a regression test)

### 3. Add to `cli.JOBS`

Edit `src/blog_digest_combined/cli.py`:

```python
JOBS = {
    "iCloud 订阅":  "ae7df3150e0e",
    "Indie 科技":  "909cbd821c57",
    "ML 博主":     "8836652e22cb",
    "HF 论文":     "hf_papers_watcher",
    "AAIF 每周":   "aaif_weekly",      # ← NEW
}
```

**Key naming**:
- `label` (left) is what shows in the doc header. Chinese-friendly label preferred (matches existing).
- `value` (right) is the actual subdirectory name under `~/.hermes/cron/output/`. Must match step 1.

### 4. Test it

Run the rollup for a past date where the new source has content:

```bash
python3 -m blog_digest_combined --today 2026-09-22
```

Check the output:

```bash
ls ~/.hermes/cron/output/combined/blog_digest_2026-09-22.*
head -50 ~/.hermes/cron/output/combined/blog_digest_2026-09-22.md
```

The new source's articles should appear under a `## AAIF 每周` heading in
both MD and HTML.

### 5. Add a regression test

The test prevents future changes from accidentally breaking your new source's
integration:

```python
# tests/test_cli.py
def test_new_source_aaif_appears_in_rollup(self, fake_hermes_env, monkeypatch):
    """Verify AAIF 每周 source articles make it into the final digest."""
    (fake_hermes_env / "aaif_weekly" / "brief.md").write_text(
        "**日期**：2026-09-23\n\n## AAIF\n\n"
        "**[1] Test Article**\n原文：https://example.com/foo\n\nc\n"
    )
    # ... (similar to other tests; mock DEFAULT_OUTPUT_BASE)
    main(["--today", "2026-09-23"])
    md_content = (fake_hermes_env / "combined" / "blog_digest_2026-09-23.md").read_text()
    assert "AAIF" in md_content
```

### 6. Deploy

```bash
pip install -e ~/projects/blog-digest-combined --upgrade
```

Cron will pick up the change on the next run. Verify by checking the next
day's digest for the new content.

## Edge cases

### What if the new source is noisy (lots of articles)?

Two options:
- **Filter at sub-cron level**: most idiomatic — let sub-cron pick the
  top-K articles. Reduces rollup work.
- **Filter at rollup level**: not currently supported. If you need it,
  add a per-source `max_articles` field to `JOBS` (then a new module +
  test).

### What if the new source's brief is empty (failed sub-cron)?

The rollup handles this gracefully — `failed_jobs` is incremented,
`[WARN] <label>: empty content` is logged, and the digest still ships with
the other sources. No special handling needed.

### What if multiple sub-crons have similar labels (e.g. "Tech 1" / "Tech 2")?

Distinguish them in the label:
- "Tech (Substack)" / "Tech (RSS)"
- "中文 Tech" / "英文 Tech"

Operators read these labels in the doc header; clarity matters.

### What if I want to skip a source temporarily (e.g. vacation)?

Comment out the entry in `JOBS` and run the rollup. The other sources
will continue working. (Better than setting `JOBS[label] = None` — explicit
None has its own subtle behavior.)