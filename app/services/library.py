from __future__ import annotations

import json
import re
from collections.abc import Sequence
from datetime import datetime
from typing import Any

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.db_models import HumanFeedback, ImageRecord, UserAnnotation
from app.services.ontology import expand_search_terms

_WS = re.compile(r"\s+")
_PUNCT = re.compile(r"^[\"'`(]+|[\"'`).,;:!?]+$")


def _norm(s: str | None) -> str:
    return (s or "").strip().lower()


def _strip_token_punct(t: str) -> str:
    s = (t or "").strip()
    # Remove common surrounding punctuation from search tokens ("foo", 'bar', etc.)
    while True:
        nxt = _PUNCT.sub("", s)
        if nxt == s:
            break
        s = nxt.strip()
    return s


def _matches_token(haystack: str, query: str) -> bool:
    q = _norm(query)
    if not q:
        return True
    h = _norm(haystack)
    for variant in expand_search_terms(q):
        v = _norm(variant)
        if v and v in h:
            return True
    return q in h


def _tokenize_search(q: str | None) -> list[str]:
    if not q or not q.strip():
        return []
    return [_strip_token_punct(t) for t in _WS.split(q.strip()) if _strip_token_punct(t)]


def _load_ai(im: ImageRecord) -> dict[str, Any] | None:
    if not im.ai_metadata_json:
        return None
    try:
        return json.loads(im.ai_metadata_json)
    except json.JSONDecodeError:
        return None


def image_search_blob(
    image: ImageRecord, ai: dict[str, Any] | None, annotations: Sequence[UserAnnotation]
) -> str:
    parts: list[str] = []
    if image.description:
        parts.append(image.description)
    if ai:
        d = ai.get("description")
        if d is not None:
            parts.append(str(d))
        attrs = ai.get("attributes") or {}
        if isinstance(attrs, dict):
            for k in (
                "garment_type",
                "style",
                "material",
                "pattern",
                "season",
                "occasion",
                "consumer_profile",
                "trend_notes",
            ):
                v = attrs.get(k)
                if v is not None:
                    parts.append(str(v))
            loc = attrs.get("location") or {}
            if isinstance(loc, dict):
                for k in ("continent", "country", "city"):
                    v = loc.get(k)
                    if v is not None:
                        parts.append(str(v))
            pal = attrs.get("color_palette")
            if isinstance(pal, list):
                for c in pal:
                    if c is not None:
                        parts.append(str(c))
    for ann in annotations:
        if ann.notes:
            parts.append(ann.notes)
        try:
            tags = json.loads(ann.tags or "[]")
            if isinstance(tags, list):
                for t in tags:
                    parts.append(str(t))
        except json.JSONDecodeError:
            pass
    return " \n ".join(parts)


def _attr_eq(ai: dict[str, Any] | None, path: list[str], value: str | None) -> bool:
    if not value or not value.strip():
        return True
    if not ai:
        return False
    attrs = ai.get("attributes")
    if not isinstance(attrs, dict):
        return False
    cur: Any = attrs
    for p in path:
        if not isinstance(cur, dict):
            return False
        cur = cur.get(p)
    if cur is None:
        return False
    return _norm(str(cur)) == _norm(value)


def _color_has(ai: dict[str, Any] | None, value: str | None) -> bool:
    if not value or not value.strip():
        return True
    if not ai:
        return False
    attrs = ai.get("attributes")
    if not isinstance(attrs, dict):
        return False
    pal = attrs.get("color_palette")
    if not isinstance(pal, list):
        return False
    vn = _norm(value)
    return any(_norm(str(c)) == vn for c in pal)


def collect_filter_options(db: Session) -> dict[str, Any]:
    images = db.query(ImageRecord).all()
    garment_type: set[str] = set()
    style: set[str] = set()
    material: set[str] = set()
    pattern: set[str] = set()
    season: set[str] = set()
    occasion: set[str] = set()
    consumer_profile: set[str] = set()
    trend_notes: set[str] = set()
    color_palette: set[str] = set()
    continent: set[str] = set()
    country: set[str] = set()
    city: set[str] = set()
    designer: set[str] = set()
    captured_year: set[int] = set()
    captured_month: set[int] = set()
    captured_season: set[str] = set()

    for im in images:
        if im.designer:
            designer.add(im.designer)
        if im.captured_year is not None:
            captured_year.add(im.captured_year)
        if im.captured_month is not None:
            captured_month.add(im.captured_month)
        if im.captured_season:
            captured_season.add(im.captured_season)
        ai = _load_ai(im)
        if not ai:
            continue
        # Only build filters from real model output (avoid polluting with mock/fallback).
        src = ai.get("source")
        if src not in ("gemini", "openai"):
            continue
        attrs = ai.get("attributes")
        if not isinstance(attrs, dict):
            continue

        def add_str(key: str, dest: set[str]) -> None:
            v = attrs.get(key)
            if v is not None and str(v).strip():
                dest.add(str(v))

        add_str("garment_type", garment_type)
        add_str("style", style)
        add_str("material", material)
        add_str("pattern", pattern)
        add_str("season", season)
        add_str("occasion", occasion)
        add_str("consumer_profile", consumer_profile)
        add_str("trend_notes", trend_notes)
        loc = attrs.get("location")
        if isinstance(loc, dict):
            for key, dest in (
                ("continent", continent),
                ("country", country),
                ("city", city),
            ):
                v = loc.get(key)
                if v is not None and str(v).strip():
                    dest.add(str(v))
        pal = attrs.get("color_palette")
        if isinstance(pal, list):
            for c in pal:
                if c is not None and str(c).strip():
                    color_palette.add(str(c))

    def sort_str(s: set[str]) -> list[str]:
        return sorted(s, key=lambda x: x.lower())

    return {
        "garment_type": sort_str(garment_type),
        "style": sort_str(style),
        "material": sort_str(material),
        "pattern": sort_str(pattern),
        "season": sort_str(season),
        "occasion": sort_str(occasion),
        "consumer_profile": sort_str(consumer_profile),
        "trend_notes": sort_str(trend_notes),
        "color_palette": sort_str(color_palette),
        "continent": sort_str(continent),
        "country": sort_str(country),
        "city": sort_str(city),
        "designer": sort_str(designer),
        "captured_year": sorted(captured_year),
        "captured_month": sorted(captured_month),
        "captured_season": sort_str(captured_season),
    }


def query_images(
    db: Session,
    q: str | None = None,
    garment_type: str | None = None,
    style: str | None = None,
    material: str | None = None,
    pattern: str | None = None,
    season: str | None = None,
    occasion: str | None = None,
    consumer_profile: str | None = None,
    trend_notes: str | None = None,
    color_palette: str | None = None,
    continent: str | None = None,
    country: str | None = None,
    city: str | None = None,
    designer: str | None = None,
    captured_year: int | None = None,
    captured_month: int | None = None,
    captured_season: str | None = None,
) -> list[ImageRecord]:
    candidates = list(db.query(ImageRecord).all())
    if designer is not None:
        candidates = [im for im in candidates if im.designer == designer]
    if captured_year is not None:
        candidates = [im for im in candidates if im.captured_year == captured_year]
    if captured_month is not None:
        candidates = [im for im in candidates if im.captured_month == captured_month]
    if captured_season is not None:
        candidates = [
            im for im in candidates if im.captured_season and im.captured_season == captured_season
        ]

    tokens = _tokenize_search(q)
    filtered: list[ImageRecord] = []

    for im in candidates:
        ai = _load_ai(im)
        anns = db.query(UserAnnotation).filter(UserAnnotation.image_id == im.id).all()
        if not _attr_eq(ai, ["garment_type"], garment_type):
            continue
        if not _attr_eq(ai, ["style"], style):
            continue
        if not _attr_eq(ai, ["material"], material):
            continue
        if not _attr_eq(ai, ["pattern"], pattern):
            continue
        if not _attr_eq(ai, ["season"], season):
            continue
        if not _attr_eq(ai, ["occasion"], occasion):
            continue
        if not _attr_eq(ai, ["consumer_profile"], consumer_profile):
            continue
        if not _attr_eq(ai, ["trend_notes"], trend_notes):
            continue
        if not _color_has(ai, color_palette):
            continue
        if not _attr_eq(ai, ["location", "continent"], continent):
            continue
        if not _attr_eq(ai, ["location", "country"], country):
            continue
        if not _attr_eq(ai, ["location", "city"], city):
            continue
        blob = image_search_blob(im, ai, anns)
        if tokens:
            if not all(_matches_token(blob, t) for t in tokens):
                continue
        filtered.append(im)

    filtered.sort(key=lambda x: x.created_at or datetime.min, reverse=True)
    return filtered


def feedback_summary_for_image(db: Session, image_id: int) -> tuple[int, float | None] | None:
    count = db.query(func.count(HumanFeedback.id)).filter(HumanFeedback.image_id == image_id).scalar()
    if not count:
        return None
    avg_rating = (
        db.query(func.avg(HumanFeedback.rating))
        .filter(HumanFeedback.image_id == image_id, HumanFeedback.rating.isnot(None))
        .scalar()
    )
    avg_f = float(avg_rating) if avg_rating is not None else None
    return int(count), avg_f
