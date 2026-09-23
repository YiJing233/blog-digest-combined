"""Tests for the CLI entry point (cli.main).

These exercise the orchestration: load jobs → parse → render → write files.
Pins the seen_urls.json end-to-end contract.
"""

from __future__ import annotations

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
