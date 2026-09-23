# Recipe: Run end-to-end test before deploying

Verify the rollup works against your real cron directories before
deploying a code change.

## When to use

- Before deploying any change to `src/blog_digest_combined/*`
- After upgrading a dependency (none currently, but future-proof)
- When debugging "why does the rollup behave differently in CI vs prod?"

## Steps

### 1. Run unit tests (fastest)

```bash
cd ~/projects/blog-digest-combined
PYTHONPATH=src python3 -m pytest tests/ -v
```

All 170 tests should pass. If any fail, don't deploy — fix first.

### 2. Run unit tests with coverage (sanity check)

```bash
PYTHONPATH=src python3 -m pytest tests/ --cov=blog_digest_combined --cov-fail-under=80
```

Coverage should be ≥80%. We're currently at 91.82%.

### 3. Run the rollup against production dirs (with --today yesterday)

Yesterday's date uses past briefs — won't pollute today's state:

```bash
python3 -m blog_digest_combined --today 2026-09-22
```

Check exit code and outputs:

```bash
# Should return 0 (success) or 2 (no content)
echo "Exit: $?"

# Should produce MD + HTML
ls ~/.hermes/cron/output/combined/blog_digest_2026-09-22.*

# Open the HTML and visually check
xdg-open ~/.hermes/cron/output/combined/blog_digest_2026-09-22.html
```

### 4. Run the rollup against a temp dir (zero production impact)

Most thorough — uses a copy of the cron output state:

```bash
TMPDIR=$(mktemp -d)
cp -r ~/.hermes/cron/output/* $TMPDIR/
# Now $TMPDIR has all the briefs + seen_urls.json (if any)

# Run the rollup with --output-dir
python3 -m blog_digest_combined \
    --today 2026-09-22 \
    --output-dir $TMPDIR

# Inspect outputs
ls $TMPDIR/combined/

# Cleanup
rm -rf $TMPDIR
```

### 5. Inspect the rollup's stdout/stderr

The rollup emits useful diagnostic info. Watch for:

- `[INFO] get_latest_md(<job>): today=... → back-day fallback to ...` — should
  only appear when today's brief is missing
- `[INFO] <label> (<job_id>): N chars clean, mtime=...` — should always
  appear, with non-zero N
- `[DEDUP] <label>: dropped N cross-day duplicate(s)` — expected for
  re-runs of yesterday's content
- `[DEDUP] <label>: dropped N cross-job duplicate(s)` — expected when same
  article appears in multiple sub-crons
- `[WARN] <label>: empty content` — only when sub-cron failed
- `[WARN] Failed jobs: ...` — only when at least one job failed
- `[WARN] Empty jobs (after dedup): ...` — only when at least one job
  dedup'd to zero articles
- `[DONE] <today> · N sections · M articles` — final summary

Any unexpected output is worth investigating before deploy.

### 6. (Optional) Diff against yesterday's output

If you ran for yesterday's date, compare against the existing
`blog_digest_2026-09-22.{md,html}`:

```bash
# Backup old output
cp ~/.hermes/cron/output/combined/blog_digest_2026-09-22.md /tmp/old.md

# Run new rollup
python3 -m blog_digest_combined --today 2026-09-22

# Diff
diff /tmp/old.md ~/.hermes/cron/output/combined/blog_digest_2026-09-22.md | head -30
```

If new output is identical (or only differs in nondeterministic fields
like timestamps), you've confirmed idempotency.

### 7. (Optional) Performance check

Time the execution:

```bash
time python3 -m blog_digest_combined --today 2026-09-22
```

Expected: < 1 second. If > 5 seconds, the regex passes or atomic writes
might be the bottleneck. Profile before deploy.

### 8. CI verification

After pushing, check the GitHub Actions run:

```
https://github.com/YiJing233/blog-digest-combined/actions
```

Latest run should show green checkmarks on:
- `pytest (Python 3.9 / 3.11 / 3.12)` × 3 (each Python version)
- `mypy (best-effort)`

If any red, fix and re-push.

## Acceptance criteria

A code change is safe to deploy if ALL of:

- [ ] All 170 tests pass (`pytest -v`)
- [ ] Coverage ≥ 80% (`--cov-fail-under=80`)
- [ ] Rollup runs cleanly for a past date (`--today 2026-09-22`)
- [ ] Output is idempotent (or only differs in expected fields)
- [ ] CI is green (all 4 matrix cells)
- [ ] No `[WARN]` lines that weren't there before (with explanation)

If you can check all 6, ship it.