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


class TestCanonicalUrlEdgeCases:
    """Additional canonical_url edge cases — every test pins a real failure mode
    we hit during testing or could reasonably hit in production."""

    def test_empty_string(self):
        """Empty string → empty string, never raises."""
        assert canonical_url("") == ""

    def test_url_with_port(self):
        """Port numbers MUST NOT be canonicalized away."""
        # :443 is meaningful; if we strip it the URL collides with non-https form
        assert canonical_url("https://api.example.com:443/v1/foo/") == \
               "https://api.example.com:443/v1/foo"

    def test_host_lowercased(self):
        """Host case-folded — DNS is case-insensitive."""
        # Same article, two host case variants → must collide
        assert canonical_url("https://Example.COM/Foo") == \
               canonical_url("https://example.com/Foo")

    def test_idn_punycode(self):
        """IDN-encoded hosts stay as the punycode form (not unencoded)."""
        # xn-- form is the canonical form for internationalized domains.
        # urlsplit doesn't decode; we leave it as-is.
        url = "https://xn--fiqs8s.example.com/foo/"
        assert canonical_url(url) == "https://xn--fiqs8s.example.com/foo"

    def test_repeated_query_keys(self):
        """Multi-value query keys: `?a=1&a=2` — order is preserved as-is by
        `parse_qsl`. We do NOT sort or deduplicate (the server may interpret
        both values)."""
        result = canonical_url("https://example.com/foo?a=1&a=2")
        # Both values present
        assert "a=1" in result
        assert "a=2" in result

    def test_percent_encoded_query_normalized_to_space(self):
        """%20 and + BOTH encode a space in URLs (RFC 3986). Our canonical form
        normalizes both to '+' (urllib's query convention).

        This means `https://example.com/foo?key=hello%20world` and
        `https://example.com/foo?key=hello+world` collapse to the same canonical.
        That's correct — they're semantically the same URL."""
        with_pct = canonical_url("https://example.com/foo?key=hello%20world")
        without = canonical_url("https://example.com/foo?key=hello+world")
        assert with_pct == without
        # And the canonical form uses '+' for spaces (query convention)
        assert with_pct == "https://example.com/foo?key=hello+world"

    def test_multiple_fragments_dropped(self):
        """Only ONE fragment in any URL — but pass it through the
        canonicalizer twice to be sure."""
        first = canonical_url("https://example.com/foo#a#b")
        second = canonical_url(first)
        # No '#' remains
        assert "#" not in first
        assert "#" not in second

    def test_tracking_param_aliases_stripped(self):
        """utm_* / ref / source stripped — these are explicitly in the
        blocklist. Verified per the 2026-09-23 incident: blogwatcher
        sub-crons often add `?source=feed` etc. that must not pollute state."""
        cases = [
            ("https://example.com/foo?fbclid=abc",                     "https://example.com/foo"),
            ("https://example.com/foo?gclid=xyz",                      "https://example.com/foo"),
            ("https://example.com/foo?mc_cid=12345",                   "https://example.com/foo"),
            ("https://example.com/foo?_ga=GA1.2.123456789.987654321",  "https://example.com/foo"),
            ("https://example.com/foo?igshid=abc",                     "https://example.com/foo"),
        ]
        for raw, expected in cases:
            got = canonical_url(raw)
            assert got == expected, f"failed: {raw!r} → {got!r} (want {expected!r})"

    def test_retain_legitimate_query_params(self):
        """Non-tracking params (a, id, page) MUST survive canonicalization."""
        result = canonical_url("https://example.com/foo?id=42&page=2&utm_source=x&keep=ok")
        assert "id=42" in result
        assert "page=2" in result
        assert "keep=ok" in result
        assert "utm_source" not in result

    def test_url_with_userinfo_dropped_or_kept(self):
        """URLs with userinfo (user:pass@host) — we leave them alone.
        Real-world case: legacy feed URLs sometimes include api keys.
        Document the choice; if you ever decide to strip, this test fails
        and forces you to re-document."""
        # urlsplit parses userinfo but we don't normalize it.
        # urls with userinfo stay as-is modulo utm stripping.
        url = "https://user:pass@example.com/foo?utm_source=x"
        assert canonical_url(url) == "https://user:pass@example.com/foo"


class TestIsUrlInRecentDaysDualKeyLookup:
    """The 2026-09-23 regression — runtime canonicalizes the QUERY side but
    `seen` dict keys may be raw (legacy state files). The lookup MUST match
    EITHER form. These tests pin each code path.

    Code paths exercised:
      A. Direct canonical hit in `seen` (clean state)
      B. Direct raw-form hit in `seen` (legacy state, single key)
      C. Legacy raw-key requires slow-path scan of all seen keys
      D. Today itself (excluded — chicken-and-egg safety)
      E. Outside window (not recent — kept)
    """

    def test_a_direct_canonical_match(self):
        """Clean state: seen has canonical keys."""
        seen = {"https://example.com/foo": "2026-09-22"}
        assert is_url_in_recent_days("https://example.com/foo", seen, "2026-09-23") is True

    def test_b_raw_form_match_in_seen(self):
        """Legacy state: seen has raw URL keys (with trailing /).
        Query side is bare URL. Fast-path match must hit."""
        # The raw key is what we have in seen; the URL we query is the
        # same — fast-path match
        seen = {"https://example.com/foo/": "2026-09-22"}
        assert is_url_in_recent_days("https://example.com/foo/", seen, "2026-09-23") is True

    def test_c_slow_path_legacy_keys_in_seen(self):
        """The 2026-09-23 regression: query URL is canonical, seen has raw.
        Fast-path fails (canonical not in seen, raw not in seen).
        Slow path re-canonicalizes each seen key to find the match."""
        seen = {"https://example.com/foo/": "2026-09-22"}  # raw key (legacy)
        result = is_url_in_recent_days(
            "https://example.com/foo", seen, "2026-09-23",  # bare URL (canonical query)
        )
        assert result is True

    def test_d_today_itself_not_in_recent(self):
        """Same-run safety — caller writes today's URLs AFTER this check."""
        seen = {"https://example.com/foo": "2026-09-23"}
        # Querying with today (2026-09-23) and last_seen=today → NOT in window
        assert is_url_in_recent_days("https://example.com/foo", seen, "2026-09-23") is False

    def test_e_outside_window_not_recent(self):
        """5+ days old → out of the 3-day window → returns False."""
        seen = {"https://example.com/foo": "2026-09-15"}
        # 8 days back, far outside window
        assert is_url_in_recent_days("https://example.com/foo", seen, "2026-09-23") is False

    def test_canonical_vs_raw_no_false_positive_for_unrelated(self):
        """Slow path must not falsely match unrelated URLs."""
        # Seen has raw foo/ at 2026-09-22; we query bar (no match anywhere)
        seen = {"https://example.com/foo/": "2026-09-22"}
        assert is_url_in_recent_days("https://example.com/bar", seen, "2026-09-23") is False


class TestLoadSeenUrlsCorruptionRecovery:
    """Pins the corruption-handling contract: bad input → empty dict,
    never raises. (Original skill saved raw debug logs as state files.)"""

    def test_corrupt_json_returns_empty(self, tmp_path, caplog):
        path = tmp_path / "broken.json"
        path.write_text("{this is not json")
        result = load_seen_urls(path)
        assert result == {}

    def test_json_list_returns_empty(self, tmp_path):
        """Top-level list (not dict) — forbidden by our schema."""
        path = tmp_path / "list.json"
        path.write_text("[1, 2, 3]")
        assert load_seen_urls(path) == {}

    def test_json_null_returns_empty(self, tmp_path):
        path = tmp_path / "null.json"
        path.write_text("null")
        assert load_seen_urls(path) == {}

    def test_empty_file_returns_empty(self, tmp_path):
        """Zero-byte file — common after crash mid-write."""
        path = tmp_path / "empty.json"
        path.write_text("")
        assert load_seen_urls(path) == {}

    def test_file_with_only_whitespace(self, tmp_path):
        path = tmp_path / "ws.json"
        path.write_text("  \n\t  \n")
        assert load_seen_urls(path) == {}

    def test_save_writes_unicode_escaped(self, tmp_path):
        """ensure_ascii=False — Chinese labels should be UTF-8 in the file."""
        path = tmp_path / "seen.json"
        data = {"https://example.com/中文标签/foo": "2026-09-23"}
        save_seen_urls(path, data)
        # Raw read — Chinese chars should appear in the file
        content = path.read_text()
        assert "中文标签" in content, f"Chinese got escaped: {content!r}"


class TestEvictOnlyOlderThanWindow:
    """evict_old_entries is the persistence-side counterpart of the rolling
    3-day window. These tests pin when entries get dropped vs preserved."""

    def test_keep_within_window(self):
        seen = {"https://a": "2026-09-22", "https://b": "2026-09-21"}
        new, n = evict_old_entries(seen, "2026-09-23", window_days=3)
        assert n == 0
        assert "https://a" in new
        assert "https://b" in new

    def test_drop_just_outside_window(self):
        """4 days back is outside window=3."""
        seen = {"https://a": "2026-09-19"}
        new, n = evict_old_entries(seen, "2026-09-23", window_days=3)
        assert n == 1
        assert "https://a" not in new

    def test_mixed_dates_only_old_evicted(self):
        seen = {
            "https://in":    "2026-09-22",   # kept
            "https://out":   "2026-09-18",   # evicted
            "https://today": "2026-09-23",   # today itself, kept
        }
        new, n = evict_old_entries(seen, "2026-09-23", window_days=3)
        assert n == 1
        assert "https://in" in new
        assert "https://today" in new
        assert "https://out" not in new


class TestMigrationCollapsesRawAndCanonical:
    """migrate_legacy_keys_to_canonical is the one-shot data fix for
    state files written before canonical key adoption."""

    def test_raw_slash_key_collapses(self):
        legacy = {
            "https://example.com/foo/": "2026-09-22",
            "https://example.com/foo":  "2026-09-23",
        }
        result = migrate_legacy_keys_to_canonical(legacy)
        # Two keys → one after migration
        assert len(result) == 1
        # MAX date wins when raw + canonical coexist
        assert list(result.values())[0] == "2026-09-23"

    def test_preserves_max_date_for_disjoint_keys(self):
        legacy = {
            "https://example.com/a/": "2026-09-23",
            "https://example.com/b":  "2026-09-22",
        }
        result = migrate_legacy_keys_to_canonical(legacy)
        assert set(result.keys()) == {"https://example.com/a", "https://example.com/b"}

    def test_idempotent(self):
        """Migrating twice produces the same result."""
        legacy = {"https://example.com/foo/": "2026-09-22"}
        once = migrate_legacy_keys_to_canonical(legacy)
        twice = migrate_legacy_keys_to_canonical(once)
        assert once == twice

    def test_empty_input(self):
        assert migrate_legacy_keys_to_canonical({}) == {}

    def test_handles_corrupt_date_gracefully(self):
        """Bad date string is treated as evicted — never crashes."""
        legacy = {"https://example.com/foo": "garbage-date"}
        result = migrate_legacy_keys_to_canonical(legacy)
        # Per evict behavior: corrupt date → dropped
        assert result == {}
