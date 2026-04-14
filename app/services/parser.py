from __future__ import annotations

import json
import re
from typing import Any

from app.services.ontology import canonicalize_field


_FENCE = re.compile(r"```(?:json)?\s*([\s\S]*?)\s*```", re.IGNORECASE)


def extract_json_blob(text: str | None) -> str:
    if not text:
        return ""
    t = text.strip()
    m = _FENCE.search(t)
    if m:
        return m.group(1).strip()
    return t


def _text_or_null(val: Any) -> str | None:
    if val is None:
        return None
    if isinstance(val, str):
        t = val.strip()
        return t if t else None
    return None


def normalize_attributes(attrs: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key in (
        "garment_type",
        "style",
        "material",
        "pattern",
        "season",
        "occasion",
        "consumer_profile",
        "trend_notes",
    ):
        raw = _text_or_null(attrs.get(key))
        if key in ("garment_type", "style", "material", "pattern", "season", "occasion"):
            out[key] = canonicalize_field(key, raw)
        else:
            out[key] = raw

    pal = attrs.get("color_palette")
    if isinstance(pal, str):
        out["color_palette"] = [pal]
    elif isinstance(pal, list):
        out["color_palette"] = [str(x) for x in pal]
    else:
        out["color_palette"] = []

    loc = attrs.get("location")
    if isinstance(loc, dict):
        out["location"] = {
            "continent": _text_or_null(loc.get("continent")),
            "country": _text_or_null(loc.get("country")),
            "city": _text_or_null(loc.get("city")),
        }
    else:
        out["location"] = {"continent": None, "country": None, "city": None}
    return out


def derive_title_from_attributes(attrs: dict[str, Any]) -> str | None:
    """Create a short, product-style title (3-7 words) from normalized attributes."""
    if not isinstance(attrs, dict):
        return None
    garment = attrs.get("garment_type")
    style = attrs.get("style")
    material = attrs.get("material")
    pattern = attrs.get("pattern")

    words: list[str] = []
    if isinstance(style, str) and style:
        words.append(style)
    if isinstance(garment, str) and garment:
        words.append(garment)
    if isinstance(pattern, str) and pattern and pattern not in ("solid",):
        # Keep it short: "striped", "floral", etc.
        words.append(pattern)

    if isinstance(material, str) and material:
        # "in wool" reads naturally and stays compact
        words.extend(["in", material])

    # Fall back
    if not words and isinstance(garment, str) and garment:
        words = [garment]
    if not words:
        return None

    # Trim to 7 words max
    title = " ".join(words[:7]).strip()
    return title or None


def parse_model_output(raw: str) -> dict[str, Any]:
    blob = extract_json_blob(raw)

    def _load_json_best_effort(s: str) -> Any:
        try:
            return json.loads(s)
        except json.JSONDecodeError:
            # Some providers return JSON with quotes escaped (e.g. { \"title\": ... }).
            if '\\"' in s and s.lstrip().startswith("{"):
                try:
                    return json.loads(s.replace('\\"', '"').replace("\\n", "\n").replace("\\t", "\t"))
                except Exception:
                    pass
            # Try extracting the outermost JSON object.
            s2 = extract_json_object_best_effort(s)
            if s2 != s:
                return json.loads(s2)
            raise

    try:
        root: Any = _load_json_best_effort(blob)
    except json.JSONDecodeError:
        # Some providers occasionally return the JSON as a quoted string.
        try:
            decoded = json.loads(blob)  # type: ignore[arg-type]
            if isinstance(decoded, str):
                root = _load_json_best_effort(decoded)
            else:
                raise
        except Exception as e:
            raise ValueError("Model returned invalid JSON") from e

    # Normalize common shapes.
    if isinstance(root, str):
        try:
            root = _load_json_best_effort(root)
        except Exception:
            raise ValueError("Model returned invalid JSON")
    if isinstance(root, list) and root and isinstance(root[0], dict):
        root = root[0]
    if not isinstance(root, dict):
        raise ValueError("Model output must be a JSON object")
    title = root.get("title")
    title_s = title.strip() if isinstance(title, str) and title.strip() else None
    desc = root.get("description")
    if not isinstance(desc, str) or not desc.strip():
        raise ValueError("Missing or invalid 'description'")

    attrs = root.get("attributes")
    if attrs is None:
        attrs = {k: v for k, v in root.items() if k != "description"}
    if not isinstance(attrs, dict):
        raise ValueError("'attributes' must be an object")

    norm_attrs = normalize_attributes(attrs)
    out: dict[str, Any] = {"description": desc.strip(), "attributes": norm_attrs}
    out["title"] = title_s or derive_title_from_attributes(norm_attrs)
    return out


def extract_json_object_best_effort(text: str | None) -> str:
    if not text:
        return ""
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end <= start:
        return text
    return text[start : end + 1]
