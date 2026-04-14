"""Pytest fixtures with isolated DB and upload directory."""

from __future__ import annotations

import importlib
import sys
from collections.abc import Generator
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(tmp_path, monkeypatch) -> Generator[TestClient, None, None]:
    db_file = tmp_path / "test.db"
    upload_dir = tmp_path / "uploads"
    upload_dir.mkdir(parents=True, exist_ok=True)

    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_file}")
    # Force-disable Gemini/OpenAI during tests even if a local .env exists.
    monkeypatch.setenv("GEMINI_API_KEY", "")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    import app.config as config_mod
    import app.database as database_mod

    config_mod.get_settings.cache_clear()
    database_mod._engine = None  # type: ignore[attr-defined]
    database_mod._SessionLocal = None  # type: ignore[attr-defined]

    import app.db_models as db_models_mod
    import app.main as main_mod

    importlib.reload(database_mod)
    importlib.reload(db_models_mod)
    importlib.reload(main_mod)

    monkeypatch.setattr(main_mod, "UPLOAD_DIR", upload_dir)
    database_mod.init_db()

    try:
        with TestClient(main_mod.app) as c:
            yield c
    finally:
        eng = getattr(database_mod, "_engine", None)
        if eng is not None:
            eng.dispose()
        config_mod.get_settings.cache_clear()
        database_mod._engine = None  # type: ignore[attr-defined]
        database_mod._SessionLocal = None  # type: ignore[attr-defined]
