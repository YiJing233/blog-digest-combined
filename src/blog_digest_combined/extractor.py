"""Extract clean content from raw cron output.

Raw cron output typically looks like:

    # Cron Job: iCloud 订阅源每日简报
    ## Prompt
    ... (large SKILL.md dump) ...
    ## Response
    **日期**：2026-09-23
    ... actual summary ...
    **执行备注**：...

Extract clean content strips everything before ## Response (the prompt dump)
and truncates at trailing "执行备注" / "共筛选" markers.
"""

from __future__ import annotations

import re
from typing import Optional

# Strict: "## Response" must be a standalone line, not inside a code fence.
_PROMPT_HEADER_RE = re.compile(r"^##\s+Prompt\s*$", re.MULTILINE)
_RESPONSE_HEADER_RE = re.compile(r"^##\s+Response\s*$", re.MULTILINE)
_FAILEDPREFIX_RE = re.compile(r"\(FAILED\)")


def extract_clean_content(raw_content: str) -> str:
    """Strip prompt header + truncate trailing execution notes.

    Skips the entire block between "## Prompt" and "## Response" (model saw
    the prompt dump but the user doesn't need it). Falls back to "from
    ## Prompt forward" if no standalone ## Response exists.

    If first line is "(FAILED)"-tagged (whole-job failure), returns "" so
    caller can skip.

    Strips trailing execution notes by trimming at the last **执行备注 /
    （共筛选 / --- line.
    """
    if not raw_content:
        return ""
    lines = raw_content.split("\n")

    # Whole-job failure: bail early
    if lines and _FAILEDPREFIX_RE.search(lines[0]):
        return ""

    # Find ## Prompt position (anchor only — we discard up to ## Response)
    prompt_idx: Optional[int] = None
    response_idx: Optional[int] = None
    in_code_fence = False

    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("```"):
            in_code_fence = not in_code_fence
            continue
        if in_code_fence:
            continue
        if stripped == "## Prompt" and prompt_idx is None:
            prompt_idx = i
        elif stripped == "## Response":
            response_idx = i
            break

    if response_idx is not None:
        content_lines = lines[response_idx + 1:]
    elif prompt_idx is not None:
        content_lines = lines[prompt_idx + 1:]
    else:
        content_lines = lines

    # Truncate trailing execution notes
    real_end: Optional[int] = None
    for i in range(len(content_lines) - 1, -1, -1):
        line = content_lines[i].strip()
        if line.startswith("**执行备注") or line.startswith("（共筛选") or line == "---":
            real_end = i
            break
    if real_end is not None:
        content_lines = content_lines[:real_end]

    return "\n".join(content_lines).strip()


# Real-brief header discriminator: first line is a date-marker, not a debug tag.
REAL_BRIEF_HEADER_RE = re.compile(r"^\*\*日期\*\*\s*[：:]")
DATE_HEADER_RE = re.compile(r"^\*\*日期\*\*[：:]\s*(\d{4}-\d{2}-\d{2})")
RAW_DEBUG_HINT_RE = re.compile(r"^#\s*Cron Job:|^##\s*Prompt\s*$", re.MULTILINE)
MAX_REAL_BRIEF_BYTES = 50 * 1024  # raw debug logs are 70-130KB; real briefs fit in 50KB
