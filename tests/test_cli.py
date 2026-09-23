"""Tests for the CLI entry point (cli.main).

These exercise the orchestration: load jobs → parse → render → write files.
Pins the seen_urls.json end-to-end contract.
"""


import json
from pathlib import Path

import pytest

from blog_digest_combined import cli


@pytest.fixture
def fake_hermes_env(tmp_path, monkeypatch):
    """Construct a fake ~/.hermes/cron/output directory with sample briefs.

    Layout:
      tmp/hermes/cron/output/
        iCloud 订阅 = ae7df3150e0e/
          brief_today.md, brief_yesterday.md, raw_debug.md
        Indie 科技 = 909cbd821c57/
          brief_today.md
        ML 博主 = 8836652e22cb/
          (empty — sim a failed sub-cron)
        combined/
          (empty — this is the output dir)
    """
    base = tmp_path / "hermes" / "cron" / "output"
    base.mkdir(parents=True)

    # iCloud brief (today)
    icloud = base / "ae7df3150e0e"
    icloud.mkdir()
    (icloud / "brief_today.md").write_text(
        "**日期**：2026-09-23\n\n"
        "## 🔬 技术深度\n\n"
        "**[1] Foo**\n"
        "原文：https://example.com/foo\n\n"
        "Foo 的内容.\n"
    )
    (icloud / "brief_yesterday.md").write_text(
        "**日期**：2026-09-22\n\n"
        "**[1] Foo (yesterday)**\n"
        "原文：https://example.com/foo\n\n"
        "Foo's content from yesterday.\n"
    )
    (icloud / "raw_debug.md").write_text(
        "# Cron Job: iCloud\n## Prompt\nthe prompt\n## Response\n"
    )

    # Indie brief (today only)
    indie = base / "909cbd821c57"
    indie.mkdir()
    (indie / "brief_today.md").write_text(
        "**日期**：2026-09-23\n\n"
        "## 🏢 产业动态\n\n"
        "**[1] Bar**\n"
        "原文：https://example.com/bar\n\n"
        "Bar's content.\n"
    )

    # ML missing (failed)
    (base / "8836652e22cb").mkdir()

    # Output dir
    (base / "combined").mkdir()

    # Force JOB_DIR_OVERRIDES to use the fake base (not real $HOME/.hermes)
    import blog_digest_combined.cli as _cli
    monkeypatch.setattr(
        _cli,
        "JOB_DIR_OVERRIDES",
        {"hf_papers_watcher": base / "hf_papers_watcher"},
    )
    monkeypatch.setattr(_cli, "DEFAULT_OUTPUT_BASE", base)
    monkeypatch.setenv("HERMES_CRON_OUTPUT", str(base))
    return base


def _load_state(path: Path) -> dict:
    return json.loads(path.read_text()) if path.exists() else {}


def _wipe_all_briefs(env_dir: Path) -> None:
    """Wipe every *.md in every job subdir of env_dir (including hf_papers_watcher)."""
    import shutil
    for d in env_dir.iterdir():
        if d.is_dir() and d.name != "combined":
            shutil.rmtree(d)
            d.mkdir()



class TestBuildSourcesData:
    def test_aggregates_today_briefs(self, fake_hermes_env):
        cli.DEFAULT_OUTPUT_BASE = fake_hermes_env
        sources, failed, empty, urls = cli.build_sources_data("2026-09-23")
        labels = {s["label"] for s in sources}
        assert "iCloud 订阅" in labels
        assert "Indie 科技" in labels
        assert "ML 博主" in labels  # failed but still in list

    def test_canonical_urls_extracted(self, fake_hermes_env):
        cli.DEFAULT_OUTPUT_BASE = fake_hermes_env
        _, _, _, urls = cli.build_sources_data("2026-09-23")
        # Foo + Bar
        assert "https://example.com/foo" in urls
        assert "https://example.com/bar" in urls


class TestMainEndToEnd:
    def test_writes_md_and_html(self, fake_hermes_env, monkeypatch):
        monkeypatch.setattr(cli, "DEFAULT_OUTPUT_BASE", fake_hermes_env)
        code = cli.main(["--today", "2026-09-23"])
        assert code == 0

        md = fake_hermes_env / "combined" / "blog_digest_2026-09-23.md"
        html = fake_hermes_env / "combined" / "blog_digest_2026-09-23.html"
        assert md.exists()
        assert html.exists()

    def test_md_contains_kept_articles(self, fake_hermes_env, monkeypatch):
        monkeypatch.setattr(cli, "DEFAULT_OUTPUT_BASE", fake_hermes_env)
        cli.main(["--today", "2026-09-23"])
        md_text = (fake_hermes_env / "combined" / "blog_digest_2026-09-23.md").read_text()
        # Foo + Bar present (both kept today)
        assert "Foo" in md_text
        assert "Bar" in md_text

    def test_seen_urls_json_persists_canonical(self, fake_hermes_env, monkeypatch):
        """The 2026-09-23 regression pinned at end-to-end level.

        After main() runs, seen_urls.json MUST contain canonical-URL keys,
        never raw URLs with trailing slashes or extra params.
        """
        monkeypatch.setattr(cli, "DEFAULT_OUTPUT_BASE", fake_hermes_env)
        cli.main(["--today", "2026-09-23"])
        seen = _load_state(fake_hermes_env / "combined" / "seen_urls.json")
        # foo + bar kept today → in state as "YYYY-MM-DD"
        assert seen.get("https://example.com/foo") == "2026-09-23"
        assert seen.get("https://example.com/bar") == "2026-09-23"
        # No raw slash variants polluting state
        for key in seen:
            assert not key.endswith("/"), f"raw key in state: {key!r}"

    def test_dedup_across_days(self, fake_hermes_env, monkeypatch):
        """Day 1 keeps Foo + Bar (last_seen=2026-09-23). Day 2 re-emits
        Foo; dedup across days should drop Foo, keeping Bar."""
        _wipe_all_briefs(fake_hermes_env)

        # Day 1 briefs (both)
        (fake_hermes_env / "ae7df3150e0e" / "brief_today.md").write_text(
            "**日期**：2026-09-23\n\n"
            "## 🔬 技术深度\n\n"
            "**[1] Foo**\n"
            "原文：https://example.com/foo\n\n"
            "Foo content.\n"
        )
        (fake_hermes_env / "909cbd821c57" / "brief_today.md").write_text(
            "**日期**：2026-09-23\n\n"
            "## 🏢 产业动态\n\n"
            "**[1] Bar**\n"
            "原文：https://example.com/bar\n\n"
            "Bar content.\n"
        )

        # Day 1 run
        cli.main(["--today", "2026-09-23"])
        seen = _load_state(fake_hermes_env / "combined" / "seen_urls.json")
        # Foo + Bar both entered state today
        assert seen.get("https://example.com/foo") == "2026-09-23"
        assert seen.get("https://example.com/bar") == "2026-09-23"

        # Day 2: iCloud re-emits Foo (should be dedup'd); Indie gets fresh Baz
        (fake_hermes_env / "ae7df3150e0e" / "brief_today.md").write_text(
            "**日期**：2026-09-24\n\n"
            "## 🔬 技术深度\n\n"
            "**[1] Foo (tomorrow)**\n"
            "原文：https://example.com/foo\n\n"
            "Foo content on tomorrow.\n"
        )
        (fake_hermes_env / "909cbd821c57" / "brief_today.md").write_text(
            "**日期**：2026-09-24\n\n"
            "## 🏢 产业动态\n\n"
            "**[1] Baz (new)**\n"
            "原文：https://example.com/baz\n\n"
            "New content on day 2.\n"
        )
        cli.main(["--today", "2026-09-24"])
        md_text = (fake_hermes_env / "combined" / "blog_digest_2026-09-24.md").read_text()
        # Foo dropped (last_seen=9-23 is yesterday from 2026-09-24)
        assert "Foo (tomorrow)" not in md_text
        # Baz keeps (new URL never seen before)
        assert "Baz" in md_text
        # Bar back-day-fallback but URL already seen → dedup'd too
        assert "Bar" not in md_text

    def test_total_zero_aborts(self, fake_hermes_env, monkeypatch):
        """When all jobs produce 0 articles, main() exits with code 2."""
        _wipe_all_briefs(fake_hermes_env)
        monkeypatch.setattr(cli, "DEFAULT_OUTPUT_BASE", fake_hermes_env)
        # cli.main() returns 2 (not raises SystemExit) on abort — caller
        # sys.exit()s only when run as a script.
        assert cli.main(["--today", "2026-09-23"]) == 2


"""End-to-end cli behavior — argv/env/atomic-write/abort paths."""


import json
import os
from pathlib import Path

import pytest

from blog_digest_combined import cli
from blog_digest_combined.cli import build_sources_data, main


# ── TestArgvAndBackfill ──────────────────────────────────────────


class TestArgvTodayOverride:
    """`--today` overrides the wall clock — for backfill & testing."""

    def test_today_argument_overrides_default(self, fake_hermes_env, monkeypatch):
        """`--today 2025-01-01` makes the rollup report on that date."""
        # Write a 2025-01-01 brief
        (fake_hermes_env / "ae7df3150e0e" / "brief.md").write_text(
            "**日期**：2025-01-01\n\n## Test\n\n**[1] Past**\n"
            "原文：https://example.com/foo\n\nPast content.\n"
        )
        # Wipe everything else
        for d in fake_hermes_env.iterdir():
            if d.is_dir() and d.name not in ("combined", "ae7df3150e0e"):
                import shutil; shutil.rmtree(d)
        monkeypatch.setattr(cli, "DEFAULT_OUTPUT_BASE", fake_hermes_env)
        monkeypatch.setattr(cli, "JOB_DIR_OVERRIDES",
                           {"hf_papers_watcher": fake_hermes_env / "hf_papers_watcher"})
        code = main(["--today", "2025-01-01"])
        assert code == 0
        # Output file is dated 2025-01-01
        assert (fake_hermes_env / "combined" / "blog_digest_2025-01-01.md").exists()

    def test_backfill_seen_urls_can_alias_future_articles(self, fake_hermes_env, monkeypatch):
        """Run main() twice for same date → seen_urls already populated
        from first run → second run drops articles seen first time."""
        # Set up one brief
        (fake_hermes_env / "ae7df3150e0e" / "brief.md").write_text(
            "**日期**：2025-01-01\n\n## Test\n\n**[1] X**\n"
            "原文：https://example.com/foo\n\nc.\n"
        )
        for d in fake_hermes_env.iterdir():
            if d.is_dir() and d.name not in ("combined", "ae7df3150e0e"):
                import shutil; shutil.rmtree(d)
        monkeypatch.setattr(cli, "DEFAULT_OUTPUT_BASE", fake_hermes_env)
        monkeypatch.setattr(cli, "JOB_DIR_OVERRIDES",
                           {"hf_papers_watcher": fake_hermes_env / "hf_papers_watcher"})

        # First run — kept
        main(["--today", "2025-01-01"])
        seen = json.loads((fake_hermes_env / "combined" / "seen_urls.json").read_text())
        assert "https://example.com/foo" in seen
        assert seen["https://example.com/foo"] == "2025-01-01"

        # Second run — same date, but seen_urls already has it
        main(["--today", "2025-01-01"])
        # Should NOT have re-added (state entry stays at 2025-01-01 — same day)
        seen2 = json.loads((fake_hermes_env / "combined" / "seen_urls.json").read_text())
        assert seen2["https://example.com/foo"] == "2025-01-01"


class TestJobDirOverrides:
    """JOB_DIR_OVERRIDES is the per-source path map. Pin it works."""

    def test_default_overrides_loads(self):
        """Module-level JOB_DIR_OVERRIDES uses DEFAULT_OUTPUT_BASE."""
        assert "hf_papers_watcher" in cli.JOB_DIR_OVERRIDES

    def test_resolved_path_under_default_base(self, monkeypatch):
        """The hf_papers_watcher override is rooted at the ORIGINAL DEFAULT_OUTPUT_BASE.

        (DOCUMENTED LIMITATION: JOB_DIR_OVERRIDES is frozen at import time, so
        mutating DEFAULT_OUTPUT_BASE later does NOT change the override path.
        This is why `build_sources_data` re-computes paths per call.)

        If you ever want lazy-resolution, swap the dict for a function.
        For now, this test pins that the override is decoupled from later
        DEFAULT_OUTPUT_BASE mutations — the value is captured at import."""
        # Document the import-time value
        expected_default = cli.JOB_DIR_OVERRIDES["hf_papers_watcher"]
        # DEFAULT_OUTPUT_BASE may be reassigned in other tests; the override
        # value is what it was at import time
        assert expected_default == Path("/home/yiking/.hermes/cron/output/hf_papers_watcher")


class TestAtomicWriteContract:
    """save_seen_urls writes to tmp + rename — never leaves a partial file."""

    def test_seen_urls_file_atomically_replaced(self, tmp_path, monkeypatch):
        """After main() runs, the seen_urls.json exists and is parseable."""
        for d in [tmp_path / "hermes" / "cron" / "output"]:
            d.mkdir(parents=True, exist_ok=True)
        (tmp_path / "hermes" / "cron" / "output" / "ae7df3150e0e").mkdir()
        (tmp_path / "hermes" / "cron" / "output" / "ae7df3150e0e" / "brief.md").write_text(
            "**日期**：2026-09-23\n\n## S\n\n**[1] x**\n"
            "原文：https://example.com/x\nc\n"
        )
        (tmp_path / "hermes" / "cron" / "output" / "combined").mkdir()
        monkeypatch.setattr(cli, "DEFAULT_OUTPUT_BASE", tmp_path / "hermes" / "cron" / "output")
        monkeypatch.setattr(cli, "JOB_DIR_OVERRIDES",
                           {"hf_papers_watcher": tmp_path / "hermes" / "cron" / "output" / "hf_papers_watcher"})
        main(["--today", "2026-09-23"])
        # File parseable
        path = tmp_path / "hermes" / "cron" / "output" / "combined" / "seen_urls.json"
        assert path.exists()
        data = json.loads(path.read_text())  # No exception
        assert "https://example.com/x" in data

    def test_no_tmp_file_left_behind(self, tmp_path, monkeypatch):
        """After main(), no `seen_urls.json.tmp` should remain."""
        for d in [tmp_path / "hermes" / "cron" / "output"]:
            d.mkdir(parents=True, exist_ok=True)
        (tmp_path / "hermes" / "cron" / "output" / "ae7df3150e0e").mkdir()
        (tmp_path / "hermes" / "cron" / "output" / "ae7df3150e0e" / "brief.md").write_text(
            "**日期**：2026-09-23\n\n## S\n\n**[1] x**\n"
            "原文：https://example.com/x\nc\n"
        )
        (tmp_path / "hermes" / "cron" / "output" / "combined").mkdir()
        monkeypatch.setattr(cli, "DEFAULT_OUTPUT_BASE", tmp_path / "hermes" / "cron" / "output")
        monkeypatch.setattr(cli, "JOB_DIR_OVERRIDES",
                           {"hf_papers_watcher": tmp_path / "hermes" / "cron" / "output" / "hf_papers_watcher"})
        main(["--today", "2026-09-23"])
        # tmp file should not linger
        leftover = tmp_path / "hermes" / "cron" / "output" / "combined" / "seen_urls.json.tmp"
        assert not leftover.exists()


class TestOutputFileNames:
    """Pins the file naming convention: blog_digest_YYYY-MM-DD.{md,html}"""

    def test_md_and_html_per_today(self, fake_hermes_env, monkeypatch):
        (fake_hermes_env / "ae7df3150e0e" / "brief_today.md").write_text(
            "**日期**：2026-09-23\n\n## S\n\n**[1] X**\n"
            "原文：https://example.com/x\nc\n"
        )
        monkeypatch.setattr(cli, "DEFAULT_OUTPUT_BASE", fake_hermes_env)
        monkeypatch.setattr(cli, "JOB_DIR_OVERRIDES",
                           {"hf_papers_watcher": fake_hermes_env / "hf_papers_watcher"})
        main(["--today", "2026-09-23"])
        combined = fake_hermes_env / "combined"
        assert (combined / "blog_digest_2026-09-23.md").exists()
        assert (combined / "blog_digest_2026-09-23.html").exists()
        assert (combined / "blog_digest_latest.html").exists()  # symlink

    def test_symlink_points_to_today(self, fake_hermes_env, monkeypatch):
        (fake_hermes_env / "ae7df3150e0e" / "brief_today.md").write_text(
            "**日期**：2026-09-23\n\n## S\n\n**[1] X**\n"
            "原文：https://example.com/x\nc\n"
        )
        monkeypatch.setattr(cli, "DEFAULT_OUTPUT_BASE", fake_hermes_env)
        monkeypatch.setattr(cli, "JOB_DIR_OVERRIDES",
                           {"hf_papers_watcher": fake_hermes_env / "hf_papers_watcher"})
        main(["--today", "2026-09-23"])
        latest = fake_hermes_env / "combined" / "blog_digest_latest.html"
        assert latest.is_symlink()
        # Resolves to today's file
        resolved = (latest.parent / os.readlink(latest)).resolve()
        assert resolved.name == "blog_digest_2026-09-23.html"


class TestEmptyJobsHandling:
    """Pins the cli behavior on partial failures (some jobs ok, some failed)."""

    def test_partial_failure_still_writes_files(self, fake_hermes_env, monkeypatch):
        """If iCloud has content but ML fails, MD + HTML still get written."""
        (fake_hermes_env / "ae7df3150e0e" / "brief_today.md").write_text(
            "**日期**：2026-09-23\n\n## S\n\n**[1] X**\n"
            "原文：https://example.com/x\nc\n"
        )
        # Ensure ML dir exists but is EMPTY (failed sub-cron)
        ml_dir = fake_hermes_env / "8836652e22cb"
        ml_dir.mkdir(exist_ok=True)
        for f in ml_dir.glob("*"):
            f.unlink()
        monkeypatch.setattr(cli, "DEFAULT_OUTPUT_BASE", fake_hermes_env)
        monkeypatch.setattr(cli, "JOB_DIR_OVERRIDES",
                           {"hf_papers_watcher": fake_hermes_env / "hf_papers_watcher"})
        code = main(["--today", "2026-09-23"])
        assert code == 0
        assert (fake_hermes_env / "combined" / "blog_digest_2026-09-23.md").exists()

    def test_total_failure_exits_nonzero(self, fake_hermes_env, monkeypatch):
        """All jobs empty → exit code 2 (caller checks return code)."""
        # Wipe all briefs
        for d in fake_hermes_env.iterdir():
            if d.is_dir() and d.name != "combined":
                import shutil
                shutil.rmtree(d)
                d.mkdir()
        monkeypatch.setattr(cli, "DEFAULT_OUTPUT_BASE", fake_hermes_env)
        assert main(["--today", "2026-09-23"]) == 2


class TestBuildSourcesData:
    """`build_sources_data` returns the right shape independent of main()."""

    def test_returns_four_lists(self, fake_hermes_env, monkeypatch):
        monkeypatch.setattr(cli, "DEFAULT_OUTPUT_BASE", fake_hermes_env)
        sources, failed, empty, urls = build_sources_data("2026-09-23")
        assert isinstance(sources, list)
        assert isinstance(failed, list)
        assert isinstance(empty, list)
        assert isinstance(urls, set)


class TestHelperOutputs:
    """Pin stdout/stderr print contracts — operators read these for debugging."""

    def test_prints_dedup_state_count(self, fake_hermes_env, monkeypatch, capsys):
        """Main emits a line with dedup state count for observability."""
        (fake_hermes_env / "ae7df3150e0e" / "brief_today.md").write_text(
            "**日期**：2026-09-23\n\n## S\n\n**[1] X**\n"
            "原文：https://example.com/x\nc\n"
        )
        monkeypatch.setattr(cli, "DEFAULT_OUTPUT_BASE", fake_hermes_env)
        monkeypatch.setattr(cli, "JOB_DIR_OVERRIDES",
                           {"hf_papers_watcher": fake_hermes_env / "hf_papers_watcher"})
        main(["--today", "2026-09-23"])
        captured = capsys.readouterr()
        assert "Cross-day dedup state" in captured.out
        assert "0 URLs" in captured.out

    def test_failed_jobs_printed(self, fake_hermes_env, monkeypatch, capsys):
        """Failed jobs emit a `[WARN] Failed jobs: ...` line."""
        for d in fake_hermes_env.iterdir():
            if d.is_dir() and d.name != "combined":
                import shutil; shutil.rmtree(d); d.mkdir()
        monkeypatch.setattr(cli, "DEFAULT_OUTPUT_BASE", fake_hermes_env)
        main(["--today", "2026-09-23"])  # exits 2; we just inspect stdout
        captured = capsys.readouterr()
        # Should list at least one failed job name
        assert "[WARN]" in captured.out
