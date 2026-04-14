from __future__ import annotations

import json

import pytest

from app.services.parser import extract_json_blob, normalize_attributes, parse_model_output


def test_extract_json_blob_fenced() -> None:
    raw = '```json\n{"description": "x", "attributes": {}}\n```'
    blob = extract_json_blob(raw)
    assert '"description"' in blob


def test_parse_model_output_minimal() -> None:
    raw = json.dumps(
        {
            "description": "A linen dress.",
            "attributes": {
                "garment_type": "dress",
                "color_palette": ["white"],
                "location": {"continent": None, "country": None, "city": None},
            },
        }
    )
    out = parse_model_output(raw)
    assert out["description"] == "A linen dress."
    assert out["attributes"]["garment_type"] == "dress"


def test_parse_model_output_canonicalizes_synonyms() -> None:
    raw = json.dumps(
        {
            "description": "A tee.",
            "attributes": {
                "garment_type": "tee",
                "style": "street",
                "material": "denim fabric",
                "pattern": "stripes",
                "season": "spring/summer",
                "occasion": "everyday",
                "color_palette": ["blue"],
                "location": {"continent": None, "country": None, "city": None},
            },
        }
    )
    out = parse_model_output(raw)
    assert out["attributes"]["garment_type"] == "t-shirt"
    assert out["attributes"]["style"] == "streetwear"
    assert out["attributes"]["material"] == "denim"
    assert out["attributes"]["pattern"] == "stripe"
    assert out["attributes"]["season"] == "summer"
    assert out["attributes"]["occasion"] == "casual"


def test_normalize_color_palette_string() -> None:
    attrs = normalize_attributes({"garment_type": "x", "color_palette": "red"})
    assert attrs["color_palette"] == ["red"]


def test_parse_missing_description() -> None:
    with pytest.raises(ValueError, match="description"):
        parse_model_output('{"attributes": {}}')
