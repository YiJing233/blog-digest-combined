"""Tests for URL canonicalization + seen_urls state.

These pin the two regressions we hit most often:

  - canonical_url:  raw URL with trailing slash vs canonical form must collide.
  - seen_urls.json: must use canonical keys, not raw URLs.

If canonical_url ever changes semantics, BOTH tests should fail loudly so
we update the dedup state migration at the same time.
"""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta

import pytest

from blog_digest_combined.dedup import (
    canonical_url,
    evict_old_entries,
    is_url_in_recent_days,
    load_seen_urls,
    migrate_legacy_keys_to_canonical,
    save_seen_urls,
)


class TestCanonicalUrl:
    """canonical_url invariants: idempotent, pure, never raises."""

    def test_strips_trailing_slash(self):
        assert canonical_url("https://example.com/foo/") == "https://example.com/foo"

    def test_keeps_root_slash(self):
        # /  →  / (not rstripped; that's the home page)
        assert canonical_url("https://example.com/") == "https://example.com/"

    def test_strips_fragment(self):
        assert canonical_url("https://example.com/foo#bar") == "https://example.com/foo"

    def test_strips_utm_params(self):
        result = canonical_url("https://example.com/foo?utm_source=x&utm_medium=y&keep=ok")
        # utm_* stripped, keep=ok retained
        assert "utm_source" not in result
        assert "utm_medium" not in result
        assert "keep=ok" in result

    def test_strips_ref_and_source_params(self):
        result = canonical_url("https://example.com/foo?ref=tw&source=hn&a=1")
        assert "ref=" not in result
        assert "source=" not in result
        assert "a=1" in result

    def test_idempotent(self):
        """canonical_url(canonical_url(x)) == canonical_url(x) for any x."""
        samples = [
            "https://example.com/foo/",
            "https://example.com/foo?utm_source=x",
            "https://example.com/foo#anchor",
            "https://example.com/?ref=tw",
        ]
        for u in samples:
            once = canonical_url(u)
            twice = canonical_url(once)
            assert once == twice, f"not idempotent for {u!r}: {once!r} vs {twice!r}"

    def test_never_raises_on_garbage(self):
        """Bad input falls through unchanged, never raises."""
        for bad in ["", None, "not-a-url", "http://", 123, object()]:
            assert canonical_url(bad) == bad  # type: ignore[arg-type]

    def test_collision_stripping_slash(self):
        """The 2026-09-23 bug: raw with / and canonical without / must collide.

        This is the assertion the original code missed. If this fails, your
        todays_kept_urls code is writing raw URL keys to seen_urls.json again.
        """
        raw = "https://sixcolors.com/post/2026/09/m6-mac-mini-review-tiny-pricey-and-powerful/"
        canon = canonical_url(raw)
        assert canon == "https://sixcolors.com/post/2026/09/m6-mac-mini-review-tiny-pricey-and-powerful"
        # Reverse collision: the bare-no-slash form canonicalizes to itself.
        assert canonical_url(canon) == canon


class TestIsUrlInRecentDays:
    """Boundary behavior: today is excluded from "recent". Critical for
    not dropping content we just wrote in this same run."""

    def test_today_itself_does_not_count(self):
        """If we wrote a URL today, dedup must NOT drop it on the same run."""
        seen = {"https://example.com/foo": "2026-09-23"}
        assert is_url_in_recent_days("https://example.com/foo", seen, "2026-09-23") is False

    def test_yesterday_counts(self):
        seen = {"https://example.com/foo": "2026-09-22"}
        assert is_url_in_recent_days("https://example.com/foo", seen, "2026-09-23") is True

    def test_three_days_ago_still_in_window(self):
        """window=3 means range [today-3, today-1] — 3-days-ago is included."""
        seen = {"https://example.com/foo": "2026-09-20"}
        assert is_url_in_recent_days("https://example.com/foo", seen, "2026-09-23") is True

    def test_four_days_ago_outside_window(self):
        seen = {"https://example.com/foo": "2026-09-19"}
        assert is_url_in_recent_days("https://example.com/foo", seen, "2026-09-23") is False

    @pytest.mark.parametrize("window", [1, 3, 5, 7])
    def test_honors_custom_window(self, window):
        """Sliding window: N days back is included iff window covers it."""
        seen = {}
        for d in range(1, window + 1):
            ts = (datetime(2026, 9, 23).date() - timedelta(days=d)).isoformat()
            seen[f"https://example.com/d{d}"] = ts
            assert is_url_in_recent_days(
                f"https://example.com/d{d}", seen, "2026-09-23", window_days=window,
            ) is True

    def test_corrupt_date_falls_through(self):
        seen = {"https://example.com/foo": "not-a-date"}
        assert is_url_in_recent_days("https://example.com/foo", seen, "2026-09-23") is False


class TestEvictOldEntries:
    def test_drops_older_than_window(self):
        seen = {
            "https://a": "2026-09-19",   # 4d old, evict
            "https://b": "2026-09-20",   # 3d old, keep
            "https://c": "2026-09-22",   # 1d old, keep
        }
        new, evicted = evict_old_entries(seen, "2026-09-23", window_days=3)
        assert evicted == 1
        assert "https://a" not in new
        assert "https://b" in new
        assert "https://c" in new


class TestSeenUrlsStateIO:
    """Round-trip + atomic write + corrupt-file tolerance."""

    def test_roundtrip(self, tmp_path):
        path = tmp_path / "seen.json"
        data = {"https://a/foo": "2026-09-23", "https://b/bar": "2026-09-22"}
        save_seen_urls(path, data)
        loaded = load_seen_urls(path)
        assert loaded == data

    def test_load_missing_returns_empty(self, tmp_path):
        assert load_seen_urls(tmp_path / "nope.json") == {}

    def test_load_corrupt_returns_empty(self, tmp_path):
        path = tmp_path / "broken.json"
        path.write_text("{not valid json")
        # Suppress expected WARN to keep test output clean
        assert load_seen_urls(path) == {}

    def test_load_non_dict_returns_empty(self, tmp_path):
        path = tmp_path / "list.json"
        path.write_text("[1, 2, 3]")
        assert load_seen_urls(path) == {}

    def test_save_sorts_keys(self, tmp_path):
        path = tmp_path / "seen.json"
        save_seen_urls(
            path,
            {"https://z.com/b": "2026-09-22", "https://a.com/a": "2026-09-23"},
        )
        body = path.read_text()
        # 'a' sorts before 'b' (sort_keys=True); keys appear in order in JSON.
        assert body.find('"https://a.com/a"') < body.find('"https://z.com/b"')


class TestMigrateLegacyKeysToCanonical:
    """The data-migration that repaired seen_urls.json after the 2026-09-23 fix."""

    def test_raw_slash_collapses_to_canonical(self):
        # Old bug state — seen_urls.json had both raw and canonical keys
        # because some entries predate the canonical-URL rule.
        legacy = {
            "https://sixcolors.com/post/.../m6-mac-mini-review-tiny-pricey-and-powerful/": "2026-09-22",
            "https://sixcolors.com/post/.../m6-mac-mini-review-tiny-pricey-and-powerful":  "2026-09-23",
        }
        migrated = migrate_legacy_keys_to_canonical(legacy)
        # Both keys collide; MAX date (2026-09-23) wins.
        assert len(migrated) == 1
        only_key = next(iter(migrated.keys()))
        assert not only_key.endswith("/"), f"key still has trailing slash: {only_key!r}"
        assert migrated[only_key] == "2026-09-23"  # MAX wins

    def test_already_canonical_is_unchanged(self):
        already_clean = {"https://example.com/foo": "2026-09-23"}
        assert migrate_legacy_keys_to_canonical(already_clean) == already_clean
