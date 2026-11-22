"""Visual Gmail search filter builder and parser (sender, category, label, inbox)."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

CATEGORIES: list[tuple[str, str]] = [
    ("", "Todas as categorias"),
    ("primary", "Principal (Primary)"),
    ("social", "Social"),
    ("promotions", "Promoções"),
    ("updates", "Atualizações"),
    ("forums", "Fóruns"),
]

_CATEGORY_KEYS = {k for k, _ in CATEGORIES if k}
_FROM_RE = re.compile(r"\bfrom:([^\s()]+)", re.IGNORECASE)
_CAT_RE = re.compile(r"\bcategory:([a-z]+)", re.IGNORECASE)
_LABEL_RE = re.compile(r'\blabel:(?:"([^"]+)"|([^\s()]+))', re.IGNORECASE)


@dataclass
class FilterSpec:
    senders: list[str] = field(default_factory=list)
    category: str = ""
    label: str = ""
    in_inbox: bool = True
    unread_only: bool = True
    extra: str = ""


def _quote_if_needed(value: str) -> str:
    value = value.strip()
    if any(c.isspace() for c in value):
        return f'"{value}"'
    return value


def build_query(spec: FilterSpec) -> str:
    """Build a valid Gmail search query from structured filter fields."""
    parts: list[str] = []
    if spec.unread_only:
        parts.append("is:unread")
    if spec.in_inbox:
        parts.append("in:inbox")

    clean_senders = [s.strip() for s in spec.senders if s.strip()]
    if len(clean_senders) == 1:
        parts.append(f"from:{clean_senders[0]}")
    elif len(clean_senders) > 1:
        joined = " OR ".join(f"from:{s}" for s in clean_senders)
        parts.append(f"({joined})")

    cat = spec.category.strip().lower()
    if cat in _CATEGORY_KEYS:
        parts.append(f"category:{cat}")

    label = spec.label.strip()
    if label:
        parts.append(f"label:{_quote_if_needed(label)}")

    extra = spec.extra.strip()
    if extra:
        parts.append(extra)

    return " ".join(parts) or "is:unread in:inbox"


def parse_query(query: str) -> FilterSpec:
    """Best-effort parse of a Gmail search query into structured ``FilterSpec`` fields."""
    rest = query.strip()
    unread_only = bool(re.search(r"\bis:unread\b", rest, re.IGNORECASE))
    rest = re.sub(r"\bis:unread\b", "", rest, flags=re.IGNORECASE)

    in_inbox = bool(re.search(r"\bin:inbox\b", rest, re.IGNORECASE))
    rest = re.sub(r"\bin:inbox\b", "", rest, flags=re.IGNORECASE)

    # Extract category:...
    category = ""
    cat_match = _CAT_RE.search(rest)
    if cat_match and cat_match.group(1).lower() in _CATEGORY_KEYS:
        category = cat_match.group(1).lower()
        rest = rest[: cat_match.start()] + rest[cat_match.end() :]

    # Extract label:...
    label = ""
    label_match = _LABEL_RE.search(rest)
    if label_match:
        label = label_match.group(1) or label_match.group(2) or ""
        rest = rest[: label_match.start()] + rest[label_match.end() :]

    # Extract from:... (both standalone and parenthesized OR group)
    senders = [m.group(1) for m in _FROM_RE.finditer(rest)]
    if senders:
        rest = re.sub(
            r"\(\s*(?:from:[^\s()]+\s*(?:OR\s+)?)*from:[^\s()]+\s*\)",
            "",
            rest,
            flags=re.IGNORECASE,
        )
        rest = _FROM_RE.sub("", rest)

    extra = re.sub(r"\s+", " ", rest).strip()
    return FilterSpec(
        senders=senders,
        category=category,
        label=label,
        in_inbox=in_inbox,
        unread_only=unread_only,
        extra=extra,
    )
