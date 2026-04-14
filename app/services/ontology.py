from __future__ import annotations

import re
from collections.abc import Mapping

_WS = re.compile(r"\s+")
_MULTI_SEP = re.compile(r"[,;]|(?:\s+/\s+)")


def _norm_key(s: str) -> str:
    return _WS.sub(" ", (s or "").strip().lower())


# Lightweight synonym → canonical maps for demo-grade consistency.
# This is intentionally small and conservative: it improves filter/search/eval stability
# without pretending to be a full fashion ontology.
GARMENT_ALIASES: dict[str, str] = {
    "tee": "t-shirt",
    "t shirt": "t-shirt",
    "tshirt": "t-shirt",
    "tee shirt": "t-shirt",
    "graphic tee": "t-shirt",
    "sneakers": "sneaker",
    "trainer": "sneaker",
    "trainers": "sneaker",
    "pullover": "sweater",
    "crewneck": "sweater",
    "jumper": "sweater",
    "slacks": "trousers",
    "slacks pants": "trousers",
}

STYLE_ALIASES: dict[str, str] = {
    "street": "streetwear",
    "urban": "streetwear",
    "minimalist": "minimal",
    "biz casual": "workwear",
    "business casual": "workwear",
}

MATERIAL_ALIASES: dict[str, str] = {
    "denim fabric": "denim",
    "jean": "denim",
    "faux-leather": "faux leather",
    "pleather": "faux leather",
    "knitted": "knit",
}

PATTERN_ALIASES: dict[str, str] = {
    "stripes": "stripe",
    "striped": "stripe",
    "plaids": "plaid",
    "checker": "check",
    "checks": "check",
}

SEASON_ALIASES: dict[str, str] = {
    "spring/summer": "summer",
    "summer/spring": "summer",
    "fall/winter": "winter",
    "winter/fall": "winter",
    "ss": "summer",
    "fw": "winter",
}

OCCASION_ALIASES: dict[str, str] = {
    "everyday": "casual",
    "daily": "casual",
    "office": "work",
    "business": "work",
    "night out": "evening",
    "party": "evening",
}


def _pick_primary_phrase(raw: str | None) -> str | None:
    if raw is None:
        return None
    s = str(raw).strip()
    if not s:
        return None
    # If the model returns a laundry list, keep the first plausible label for filtering.
    parts = [p.strip() for p in _MULTI_SEP.split(s) if p.strip()]
    return parts[0] if parts else s


def canonicalize_field(field: str, value: str | None) -> str | None:
    v = _pick_primary_phrase(value)
    if v is None:
        return None
    key = _norm_key(v)
    if not key:
        return None

    if field == "season":
        # Handle composite season phrases before splitting/picking a primary token.
        if key in SEASON_ALIASES:
            return SEASON_ALIASES[key]
        if "/" in key:
            left, right = [p.strip() for p in key.split("/", 1)]
            if left in ("spring", "summer", "fall", "winter") and right in ("spring", "summer", "fall", "winter"):
                # Prefer summer/winter heuristics for common fashion shorthand.
                if {left, right} == {"spring", "summer"}:
                    return "summer"
                if {left, right} == {"fall", "winter"}:
                    return "winter"

    table: Mapping[str, str]
    if field == "garment_type":
        table = GARMENT_ALIASES
    elif field == "style":
        table = STYLE_ALIASES
    elif field == "material":
        table = MATERIAL_ALIASES
    elif field == "pattern":
        table = PATTERN_ALIASES
    elif field == "season":
        table = SEASON_ALIASES
    elif field == "occasion":
        table = OCCASION_ALIASES
    else:
        return v

    return table.get(key, v)


def expand_search_terms(term: str) -> list[str]:
    """Expand a single search token with known synonyms (keyword search helper)."""
    t = (term or "").strip()
    if not t:
        return []
    out: list[str] = [t]
    k = _norm_key(t)

    def add_from_map(m: Mapping[str, str]) -> None:
        if k in m:
            out.append(m[k])
        for alias, canon in m.items():
            if k == _norm_key(canon):
                out.append(alias)
                out.append(canon)

    add_from_map(GARMENT_ALIASES)
    add_from_map(STYLE_ALIASES)
    add_from_map(MATERIAL_ALIASES)
    add_from_map(PATTERN_ALIASES)
    add_from_map(SEASON_ALIASES)
    add_from_map(OCCASION_ALIASES)

    # De-dupe while preserving order
    seen: set[str] = set()
    uniq: list[str] = []
    for x in out:
        x = x.strip()
        if not x:
            continue
        lk = x.lower()
        if lk in seen:
            continue
        seen.add(lk)
        uniq.append(x)
    return uniq
