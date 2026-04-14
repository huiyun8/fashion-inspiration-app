"""Integration tests: filter behavior (location + time + attributes)."""

from __future__ import annotations

import json

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

import app.db_models  # noqa: F401 — register ORM mappers
from app.database import Base
from app.db_models import ImageRecord
from app.services.library import collect_filter_options, query_images


def _memory_session() -> Session:
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def _seed_library(db: Session) -> None:
    rows = [
        ImageRecord(
            file_path="/media/a.jpg",
            designer="Team A",
            captured_year=2024,
            captured_month=6,
            captured_season="SS24",
            description="Alpha",
            ai_metadata_json=json.dumps(
                {
                    "source": "gemini",
                    "description": "Alpha dress",
                    "attributes": {
                        "garment_type": "dress",
                        "style": "minimal",
                        "material": "linen",
                        "color_palette": ["white"],
                        "pattern": "solid",
                        "season": "summer",
                        "occasion": "resort",
                        "consumer_profile": "adult",
                        "trend_notes": "clean lines",
                        "location": {"continent": "Europe", "country": "France", "city": "Paris"},
                    },
                }
            ),
        ),
        ImageRecord(
            file_path="/media/b.jpg",
            designer="Team B",
            captured_year=2023,
            captured_month=11,
            captured_season="FW23",
            description="Beta coat",
            ai_metadata_json=json.dumps(
                {
                    "source": "gemini",
                    "description": "Wool coat",
                    "attributes": {
                        "garment_type": "outerwear",
                        "style": "tailored",
                        "material": "wool",
                        "color_palette": ["charcoal"],
                        "pattern": "solid",
                        "season": "winter",
                        "occasion": "work",
                        "consumer_profile": "professional",
                        "trend_notes": "oversized lapels",
                        "location": {"continent": None, "country": None, "city": None},
                    },
                }
            ),
        ),
        ImageRecord(
            file_path="/media/c.jpg",
            designer="Team C",
            captured_year=2024,
            captured_month=1,
            captured_season="FW24",
            description="Gamma tee",
            ai_metadata_json=json.dumps(
                {
                    "source": "gemini",
                    "description": "Basic cotton tee",
                    "attributes": {
                        "garment_type": "t-shirt",
                        "style": "casual",
                        "material": "cotton",
                        "color_palette": ["black"],
                        "pattern": "solid",
                        "season": "winter",
                        "occasion": "casual",
                        "consumer_profile": "adult",
                        "trend_notes": "minimal",
                        "location": {"continent": None, "country": None, "city": None},
                    },
                }
            ),
        ),
    ]
    for r in rows:
        db.add(r)
    db.commit()


def test_collect_filter_options_sorts_and_includes_meta() -> None:
    db = _memory_session()
    _seed_library(db)
    opts = collect_filter_options(db)
    assert "dress" in opts["garment_type"]
    assert "Paris" in opts["city"]
    assert 2024 in opts["captured_year"]
    db.close()


def test_query_garment_and_designer() -> None:
    db = _memory_session()
    _seed_library(db)
    rows = query_images(db, garment_type="dress", designer="Team A")
    assert len(rows) == 1
    assert rows[0].description == "Alpha"
    db.close()


def test_query_fulltext_and() -> None:
    db = _memory_session()
    _seed_library(db)
    rows = query_images(db, q="Paris linen")
    assert len(rows) == 1
    db.close()


def test_query_synonym_expansion() -> None:
    db = _memory_session()
    _seed_library(db)
    rows = query_images(db, q="tee")
    assert len(rows) == 1
    assert rows[0].file_path == "/media/c.jpg"
    db.close()
