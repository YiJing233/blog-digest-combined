"""URL canonicalization + cross-day dedup helpers.

两个职责:
  - canonical_url(): 把 URL 格式小变体归一为 stable key (抗 utm/fragment/末尾斜杠)
  - seen_urls.json 读写 + is_url_in_recent_days(): 跨日去重 state

设计契约:
  - canonical_url() 必须 idempotent: canonical_url(canonical_url(x)) == canonical_url(x)
  - canonical_url() 必须纯函数: 不抛异常,失败 fallback 输入原值
  - load_seen_urls() 损坏文件 fallback 空 dict (不抛)
  - save_seen_urls() 必须 atomic (tmp + rename),避免半截文件污染下次启动
"""

from __future__ import annotations

import json
import re
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


def canonical_url(u: str) -> str:
    """Canonicalize URL: strip utm_*/ref/source params, trailing slash, fragment.

    Examples:
        >>> canonical_url("https://example.com/foo/?utm_source=x&ref=y#bar")
        'https://example.com/foo'
        >>> canonical_url(canonical_url("https://example.com/foo/?utm_source=x")) == \
        ...     canonical_url("https://example.com/foo")
        True

    Failure modes: returns the input unchanged on any exception.
    """
    if not isinstance(u, str) or not u:
        return u
    try:
        sp = urlsplit(u)
        sp = sp._replace(fragment="")
        path = sp.path.rstrip("/") if sp.path != "/" else sp.path
        qs = parse_qsl(sp.query, keep_blank_values=True)
        qs = [
            (k, v) for k, v in qs
            if not k.lower().startswith("utm_") and k.lower() not in ("ref", "source")
        ]
        new_q = urlencode(qs)
        return urlunsplit((sp.scheme, sp.netloc, path, new_q, ""))
    except Exception:
        return u


# ── seen_urls.json state ────────────────────────────────────────

def load_seen_urls(path: Path | str) -> dict[str, str]:
    """Load seen_urls state from JSON. Returns {} on missing/corrupted file.

    Schema: {canonical_url: "YYYY-MM-DD", ...}
    """
    p = Path(path)
    if not p.exists():
        return {}
    try:
        with p.open(encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            print(f"[WARN] {p} is not a dict, ignoring", file=sys.stderr)
            return {}
        return data
    except (json.JSONDecodeError, OSError) as e:
        print(f"[WARN] {p} unreadable ({e}), ignoring", file=sys.stderr)
        return {}


def save_seen_urls(path: Path | str, data: dict[str, str]) -> None:
    """Atomic write: tmp + rename, so a crash mid-write doesn't corrupt state."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2, sort_keys=True)
    tmp.replace(p)


def is_url_in_recent_days(
    url: str,
    seen: dict[str, str],
    today: str,
    window_days: int = 3,
) -> bool:
    """True iff URL was seen in (today - window_days, today) — today itself excluded.

    Looks up by canonical URL, but ALSO matches if the seen_dict key is a
    legacy raw-URL form of the same article (e.g. trailing slash variant).
    This protects against state files written before canonicalization was
    enforced (2026-09-23 migration).

    Correctness notes:
      - Range [today - window_days, today - 1], NOT inclusive of today.
      - If `today` is itself in `seen`, we DO NOT deduplicate — that would discard
        everything we just wrote this run (chicken-and-egg). The caller writes
        today's URLs to seen AFTER this check runs.

    Date strings are ISO format "YYYY-MM-DD"; corrupt dates fall through as
    "not seen" so a bad entry never blocks content forever.
    """
    if not url:
        return False
    try:
        today_d = datetime.strptime(today, "%Y-%m-%d").date()
        cutoff = today_d - timedelta(days=window_days)
    except ValueError:
        return False

    canonical = canonical_url(url)

    # Fast path: direct canonical hit
    for key in (url, canonical):
        if key in seen:
            try:
                last_seen = datetime.strptime(seen[key], "%Y-%m-%d").date()
            except ValueError:
                return False
            return cutoff <= last_seen < today_d

    # Slow path: legacy seen_dict may have raw URL keys. Find any key whose
    # canonical form matches our canonical URL.
    for seen_key, seen_date in seen.items():
        if seen_key == canonical or seen_key == url:
            continue  # already checked
        if canonical_url(seen_key) == canonical:
            try:
                last_seen = datetime.strptime(seen_date, "%Y-%m-%d").date()
            except ValueError:
                return False
            if cutoff <= last_seen < today_d:
                return True
    return False


def evict_old_entries(
    seen: dict[str, str], today: str, window_days: int = 3,
) -> tuple[dict[str, str], int]:
    """Drop entries with last_seen < today - window_days.

    Returns (new_state, evicted_count).
    """
    try:
        today_d = datetime.strptime(today, "%Y-%m-%d").date()
        cutoff = today_d - timedelta(days=window_days)
    except ValueError:
        return seen, 0
    out = {u: d for u, d in seen.items() if _try_parse(d, cutoff)}
    return out, len(seen) - len(out)


def _try_parse(date_str: str, cutoff: date) -> bool:
    """True iff date_str parses to a date >= cutoff.

    Corrupt entries treated as evicted (don't keep poisoned data forever).
    """
    try:
        d = datetime.strptime(date_str, "%Y-%m-%d").date()
    except ValueError:
        return False
    return d >= cutoff


def migrate_legacy_keys_to_canonical(seen: dict[str, str]) -> dict[str, str]:
    """Best-effort migration: re-key raw-URL entries to their canonical form.

    When multiple entries collapse to the same canonical key, keep the MAX date.

    This repairs state files written before we adopted the canonical-URL rule
    (2026-09-23): without migration, old raw-URL keys would never deduplicate
    with new canonical keys.
    """
    new: dict[str, str] = {}
    for raw_url, date_str in seen.items():
        c = canonical_url(raw_url)
        if c in new:
            new[c] = max(new[c], date_str)
        else:
            new[c] = date_str
    return new
