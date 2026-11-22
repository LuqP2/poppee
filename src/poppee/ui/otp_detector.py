"""Heuristic detector for email verification / OTP / 2FA confirmation codes (PT-BR & EN).

Pure Python with zero Qt dependencies so it is fast and fully unit-testable headless.
"""

from __future__ import annotations

import html
import re

_HTML_SCRIPT_STYLE_RE = re.compile(r"<(script|style)\b[^>]*>.*?</\1>", re.IGNORECASE | re.DOTALL)
_HTML_TAG_RE = re.compile(r"<[^>]+>")
_URL_RE = re.compile(r"https?://\S+", re.IGNORECASE)

# Keywords that indicate a verification / confirmation / 2FA context (PT-BR & EN).
_KEYWORDS = (
    r"c[óo]digo(?:\s+de\s+(?:verifica[çc][ãa]o|confirma[çc][ãa]o|seguran[çc]a|acesso|login|uso\s+[úu]nico|autentica[çc][ãa]o))?",
    r"verification\s+code",
    r"confirmation\s+code",
    r"security\s+code",
    r"sign[\s-]?in\s+code",
    r"login\s+code",
    r"access\s+code",
    r"one[\s-]?time\s+(?:code|passcode|password)",
    r"passcode",
    r"otp",
    r"2fa",
    r"pin(?:\s+code|\s+de\s+acesso)?",
    r"token(?:\s+de\s+(?:acesso|verifica[çc][ãa]o|confirma[çc][ãa]o|seguran[çc]a))?",
    r"verifique\s+seu",
    r"confirmar\s+(?:seu|sua|o|a)",
    r"autentica[çc][ãa]o",
    r"verify\s+your",
    r"confirm\s+your",
)
_KEYWORD_RE = re.compile(r"\b(?:" + "|".join(_KEYWORDS) + r")\b", re.IGNORECASE)

# 1) Known prefixed codes like Google "G-839201" or Facebook "FB-12345".
_PREFIXED_CODE_RE = re.compile(r"\b((?:G|FB)-\d{5,8})\b")

# 2) Explicit keyword followed closely by separator and numeric or alphanumeric code.
_EXPLICIT_NUMERIC_RE = re.compile(
    r"\b(?:" + "|".join(_KEYWORDS) + r")\b"
    r"[^0-9A-Za-z\n]{0,24}"
    r"(?:(?:[ée]|is|seja|:|-|—)\s*)?"
    r"(?<!\d)(\d{3}[\s-]\d{3}|\d{4}[\s-]\d{4}|\d{4,8})(?!\d)",
    re.IGNORECASE,
)

# Alphanumeric code (5-8 chars, must contain at least one digit) after explicit separator.
_EXPLICIT_ALNUM_RE = re.compile(
    r"\b(?:" + "|".join(_KEYWORDS) + r")\b"
    r"\s*(?::|[ée]\b|is\b|—|-)\s*"
    r"([A-Z0-9]{5,8})\b",
    re.IGNORECASE,
)

# 3) Standalone numeric code (4-8 digits or 3+3 / 4+4 grouped) used in proximity to a keyword.
_STANDALONE_NUMERIC_RE = re.compile(
    r"(?<![#\d/$€£])(\d{3}[\s-]\d{3}|\d{4}[\s-]\d{4}|\d{4,8})(?!\d)"
)

_CURRENCY_BEFORE_RE = re.compile(r"(?:R\$|\$|€|£|USD|BRL)\s*$", re.IGNORECASE)
_ORDER_BEFORE_RE = re.compile(
    r"(?:pedido|order|invoice|fatura|protocolo|chamado|ticket|cep)\s*#?\s*$",
    re.IGNORECASE,
)
_DATE_OR_TIME_AROUND_RE = re.compile(r"^[/:.\-]\d|\d[/:.\-]$")


def strip_html(raw: str) -> str:
    """Convert HTML or plain text into clean searchable text."""
    if "<" not in raw:
        return html.unescape(raw)
    cleaned = _HTML_SCRIPT_STYLE_RE.sub(" ", raw)
    cleaned = re.sub(r"<(?:br|p|div|tr|li|h[1-6])\b[^>]*>", "\n", cleaned, flags=re.IGNORECASE)
    cleaned = _HTML_TAG_RE.sub(" ", cleaned)
    return html.unescape(cleaned)


def _normalize_code(raw: str) -> str:
    raw = raw.strip()
    if _PREFIXED_CODE_RE.fullmatch(raw):
        return raw.upper()
    # Strip internal spaces/hyphens from grouped numeric codes like "482 910" or "482-910".
    if re.fullmatch(r"\d+[\s-]\d+", raw):
        return re.sub(r"[\s-]+", "", raw)
    return raw


def _is_false_positive(text: str, start: int, end: int, code: str, *, strict_year: bool) -> bool:
    before = text[max(0, start - 20) : start]
    after = text[end : min(len(text), end + 12)]

    # Reject currency values ("R$ 1500", "$2000"), percentages ("100%"), dates/times ("22/11/2026").
    if _CURRENCY_BEFORE_RE.search(before):
        return True
    if after.startswith("%"):
        return True
    if (before and before[-1] in "/:") or (after and after[0] in "/:"):
        return True
    if _ORDER_BEFORE_RE.search(before):
        return True
    if before.endswith("#"):
        return True

    digits = re.sub(r"[\s-]+", "", code)
    # Reject standalone 4-digit years (e.g. 2024, 2026) unless explicitly labeled.
    if strict_year and len(digits) == 4 and digits.isdigit():
        year = int(digits)
        if 1990 <= year <= 2035:
            return True

    return False


def _search_text(text: str) -> str | None:
    if not text or not text.strip():
        return None

    # Remove URLs so query params / IDs inside links never trigger false matches.
    clean = _URL_RE.sub(" ", text)

    # 1. Prefixed codes (e.g. G-839201) — high confidence even without extra keywords.
    m = _PREFIXED_CODE_RE.search(clean)
    if m:
        return _normalize_code(m.group(1))

    # Must have at least one verification/confirmation keyword in the text.
    kw_matches = list(_KEYWORD_RE.finditer(clean))
    if not kw_matches:
        return None

    # 2. Explicit keyword immediately followed by numeric code.
    for m in _EXPLICIT_NUMERIC_RE.finditer(clean):
        raw = m.group(1)
        if not _is_false_positive(clean, m.start(1), m.end(1), raw, strict_year=False):
            return _normalize_code(raw)

    # 3. Explicit keyword + separator + alphanumeric code (must contain at least 1 digit).
    for m in _EXPLICIT_ALNUM_RE.finditer(clean):
        raw = m.group(1)
        if any(ch.isdigit() for ch in raw) and not _is_false_positive(
            clean, m.start(1), m.end(1), raw, strict_year=False
        ):
            return _normalize_code(raw)

    # 4. Standalone numeric code near a verification keyword (e.g. on the next line).
    best_code: str | None = None
    best_dist = 10**9
    for m in _STANDALONE_NUMERIC_RE.finditer(clean):
        raw = m.group(1)
        if _is_false_positive(clean, m.start(1), m.end(1), raw, strict_year=True):
            continue
        for kw in kw_matches:
            # Prefer codes appearing shortly after the keyword (<=180 chars) or before (<=80).
            if m.start(1) >= kw.end():
                dist = m.start(1) - kw.end()
                limit = 180
            else:
                dist = kw.start() - m.end(1)
                limit = 80
            if dist <= limit and dist < best_dist:
                best_dist = dist
                best_code = _normalize_code(raw)
    return best_code


def extract_verification_code(subject: str, body: str = "") -> str | None:
    """Extract a confirmation/OTP/2FA code from ``subject`` and/or ``body``."""
    # Check subject first (fastest & highest signal).
    code = _search_text(subject)
    if code:
        return code

    if body:
        plain = strip_html(body)
        # Try combined subject + body so a keyword in the subject can match a code in the body.
        code = _search_text(plain)
        if code:
            return code
        if subject:
            return _search_text(f"{subject}\n{plain}")
    return None
