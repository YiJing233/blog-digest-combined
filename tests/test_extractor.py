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
