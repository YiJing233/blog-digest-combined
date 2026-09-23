"""Tests for extract_clean_content — strip prompt headers, truncate trailing notes."""

from __future__ import annotations

from blog_digest_combined.extractor import extract_clean_content


class TestStripPrompt:
    def test_strips_between_prompt_and_response(self):
        raw = """# Cron Job: foo
**Job ID:** abc
## Prompt
[large prompt dump here]
## Response
**日期**：2026-09-23

## 🔬 Section

**[1] Article**
content
"""
        clean = extract_clean_content(raw)
        assert "## Prompt" not in clean
        assert "[large prompt dump here]" not in clean
        assert "**日期**：2026-09-23" in clean
        assert "**[1] Article**" in clean
        assert "content" in clean

    def test_failed_prefix_returns_empty(self):
        raw = "# Cron Job: foo (FAILED)\nNo content here"
        assert extract_clean_content(raw) == ""

    def test_handles_code_fence_with_response_header(self):
        """## Response inside a code fence should NOT be detected as the marker."""
        raw = """## Prompt
```
## Response
```
echo "should not match"

## Response
the real one
"""
        clean = extract_clean_content(raw)
        # The fake "## Response" in code fence is skipped; only the real one triggers
        assert clean.startswith("the real one")


class TestStripTrailing:
    def test_trims_at_execution_marker(self):
        raw = """## Response
real content

**执行备注**
n=12
"""
        clean = extract_clean_content(raw)
        assert "real content" in clean
        assert "**执行备注**" not in clean
        assert "n=12" not in clean

    def test_trims_at_dashed_separator(self):
        raw = """## Response
paragraph one

---

paragraph two
"""
        # Note: --- is also detected as trailing marker — last one cuts off
        clean = extract_clean_content(raw)
        # Behavior: trailing --- detected → content lines cut at the last ---
        # In this case the last --- is just before "paragraph two"; trim keeps up to the last ---
        assert "paragraph two" not in clean
        assert "paragraph one" in clean


class TestEdgeCases:
    def test_empty_input(self):
        assert extract_clean_content("") == ""

    def test_no_prompt_marker(self):
        """No ## Prompt / ## Response at all → returns input as-is (after trailing trim)."""
        raw = "just some text"
        clean = extract_clean_content(raw)
        assert "just some text" in clean


class TestMultipleResponseMarkers:
    """`## Response` may appear in the prompt itself (e.g. as an example).
    The extractor must use the FIRST non-code-fence `## Response` after
    `## Prompt` (or, if no `## Prompt` exists, the first `## Response` anywhere).

    But ALSO: if `## Response` is a sentinel in the agent's workflow
    (e.g. chained agents), the SECOND occurrence matters. Pin that we
    take the FIRST post-prompt marker, even if it appears multiple times."""

    def test_multiple_response_markers_take_first(self):
        raw = """# Cron Job: test
## Prompt
prompt body here, with the words "## Response" mentioned
## Response
real content starts here
## Response
later duplicated
which should be cropped
"""
        clean = extract_clean_content(raw)
        # First `## Response` is the sentinel — content begins AFTER it
        assert "real content starts here" in clean
        # Text after the second `## Response` is part of content (not stripped)
        # because we only skip UP TO the first one. Document this.
        assert "later duplicated" in clean

    def test_response_in_prompt_text_only_no_real(self):
        """`## Response` only mentioned in prompt — must NOT trigger."""
        raw = """## Prompt
This task uses ## Response as a sentinel:
```
## Response
```
## Response
actual content
"""
        clean = extract_clean_content(raw)
        # The fake `## Response` is inside a code fence — skipped
        # The real `## Response` triggers content extraction
        assert "actual content" in clean


class TestFallbackWhenNoResponseMarker:
    """If `## Prompt` exists but no `## Response`, fall back to "from Prompt+1
    forward". This handles a class of sub-crons that emit raw output without
    the sentinel header."""

    def test_prompt_only_no_response(self):
        """`## Prompt` without `## Response` — current contract: keep
        everything AFTER the `## Prompt` marker as content.

        This is a known-acceptable behavior because LLM agents in our cron
        pipeline DO include a `## Response` marker; if any future agent
        bypasses it, the extractor falls open to text after the prompt."""
        raw = """# Cron Job: test
## Prompt
This is the prompt the model saw.

But there's no ## Response marker after this — the model just dumped content
inline as if responding.
"""
        clean = extract_clean_content(raw)
        # Both must be present (current contract)
        assert "This is the prompt" in clean
        assert "the model just dumped content" in clean

    def test_no_prompt_marker_either(self):
        """Neither marker present — return as-is (after trailing notes trim)."""
        raw = "just some text\nthat has no markers at all"
        clean = extract_clean_content(raw)
        # No trimming happens (no sentinel to trigger); we keep the body.
        assert "just some text" in clean


class TestTrailingMarker:
    """Trailing trim: cutoff at the LAST `**执行备注`/`（共筛选`/`---` line.
    Pin the subtle behaviors: only trailing --- cuts, interior --- does not."""

    def test_interior_dashes_kept_but_trailing_dropped(self):
        """Current contract: trim cuts at the LAST `---` line.
        Everything before the LAST `---` is kept (including any interior
        `---` separators between paragraphs)."""
        raw = """## Response
paragraph 1

---

paragraph 2 (kept — it's BEFORE the last ---)

---

trailing-block (dropped — it's AFTER the last ---)
"""
        clean = extract_clean_content(raw)
        # Per actual behavior
        assert "paragraph 1" in clean
        assert "paragraph 2 (kept" in clean
        assert "trailing-block" not in clean

    def test_only_last_dash_separator_trims(self):
        raw = """## Response
content

---

still content

---

trailing
"""
        clean = extract_clean_content(raw)
        # Multiple `---` — the LAST one in the file is what triggers trim
        assert "trailing" not in clean
        assert "still content" in clean


class TestUnicodeAndCjk:
    """CJK handling — every byte must round-trip; no BOM, no truncation."""

    def test_chinese_content_preserved(self):
        raw = """## Response
**日期**：2026-09-23

## 🔬 技术深度

**[1] 中文标题**
原文：https://example.com/foo

背景：foo 的背景。核心观点：bar。
"""
        clean = extract_clean_content(raw)
        # ALL Chinese characters must appear intact
        assert "中文标题" in clean
        assert "技术深度" in clean
        assert "背景" in clean
        assert "核心观点" in clean
        assert "https://example.com/foo" in clean

    def test_em_dash_and_unicode_symbols(self):
        raw = """## Response
em — dash and • bullet and 🔬 emoji all preserved
中文 ─ 中文 ── 中文
"""
        clean = extract_clean_content(raw)
        assert "—" in clean
        assert "•" in clean
        assert "🔬" in clean
        assert "─" in clean


class TestFailedMarkerPosition:
    """`(FAILED)` is the whole-job-failure sentinel. Pin position-sensitive
    behavior: it's currently checked on line 1 only. Document that, and
    pin the behavior so it doesn't silently change."""

    def test_failed_on_first_line(self):
        raw = """# Cron Job: iCloud 订阅 (FAILED)
Some error happened
## Response
should not be parsed
"""
        assert extract_clean_content(raw) == ""

    def test_failed_marker_in_first_line_still_triggers(self):
        """`(FAILED)` somewhere in line 1 still triggers whole-job bail-out."""
        # Make the marker unambiguous (not embedded in another word)
        raw = """# Cron Job: iCloud 订阅 (FAILED) retry
stuff
"""
        assert extract_clean_content(raw) == ""

    def test_failed_marker_with_chinese_context_does_not_truncate(self):
        """`(FAILED)` only in line 2+ does NOT trigger — current contract is
        first-line only."""
        raw = """# Cron Job: iCloud 订阅
some status (FAILED) appears mid-output
## Response
actual content
"""
        clean = extract_clean_content(raw)
        assert "actual content" in clean

    def test_failed_on_later_line_does_not_trigger(self):
        """`(FAILED)` on line 5 should NOT treat the job as failed
        (might just be commented text)."""
        raw = """# Cron Job: iCloud 订阅
Started normally.
Then something (FAILED) later in stdout.
## Response
actual content
"""
        clean = extract_clean_content(raw)
        # Per current implementation: only line 1 is checked
        assert "actual content" in clean
