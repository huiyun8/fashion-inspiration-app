from __future__ import annotations

import json
import re
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
import httpx
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import get_db, init_db
from app.db_models import HumanFeedback, ImageRecord, UserAnnotation
from app.schemas import (
    AnnotationCreate,
    AnnotationStateUpdate,
    FeedbackCreate,
    FeedbackOut,
    FeedbackSummary,
    FilterOptions,
    ImageOut,
    LibraryMetadataUpdate,
)
from app.services.classifier import classify_image_bytes
from app.services.library import collect_filter_options, feedback_summary_for_image, query_images
from app.services.parser import derive_title_from_attributes

STATIC_DIR = Path(__file__).resolve().parent / "static"
UPLOAD_DIR = get_settings().upload_dir


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    yield


app = FastAPI(title="Fashion Inspiration Library", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _safe_filename(name: str) -> str:
    base = Path(name).name
    if not re.match(r"^[a-zA-Z0-9._-]+$", base):
        raise HTTPException(status_code=400, detail="Invalid filename")
    return base


def _filename_from_file_path(file_path: str) -> str | None:
    # expected: "/media/<safe>"
    try:
        p = Path(file_path)
        return p.name
    except Exception:
        return None


def _feedback_summary_for_image(db: Session, image_id: int) -> FeedbackSummary | None:
    row = feedback_summary_for_image(db, image_id)
    if row is None:
        return None
    count, avg = row
    return FeedbackSummary(count=count, avg_rating=avg)


def _to_feedback_out(row: HumanFeedback, include_ai_snapshot: bool = False) -> FeedbackOut:
    corr = None
    if row.corrected_attributes_json:
        try:
            corr = json.loads(row.corrected_attributes_json)
        except json.JSONDecodeError:
            corr = None
    snap = None
    if include_ai_snapshot and row.ai_snapshot_json:
        try:
            snap = json.loads(row.ai_snapshot_json)
        except json.JSONDecodeError:
            snap = None
    return FeedbackOut(
        id=row.id,
        image_id=row.image_id,
        rating=row.rating,
        comment=row.comment,
        corrected_attributes=corr,
        model_label=row.model_label,
        ai_snapshot=snap,
        created_at=row.created_at,
    )


def _to_image_out(im: ImageRecord, db: Session, *, include_feedback_summary: bool = False) -> ImageOut:
    ai_attrs = None
    ai_title = None
    ai_source = "unknown"
    if im.ai_metadata_json:
        try:
            blob = json.loads(im.ai_metadata_json)
            ai_attrs = blob.get("attributes")
            ai_title = blob.get("title") if isinstance(blob.get("title"), str) else None
            ai_source = blob.get("source") if isinstance(blob.get("source"), str) else "unknown"
        except json.JSONDecodeError:
            ai_attrs = None
    if ai_source == "unknown" and isinstance(im.description, str) and im.description.startswith("Mock classification"):
        ai_source = "mock"
    if not ai_title and isinstance(ai_attrs, dict):
        ai_title = derive_title_from_attributes(ai_attrs)
    anns = db.query(UserAnnotation).filter(UserAnnotation.image_id == im.id).all()
    user_tags: list[str] = []
    user_notes: list[str] = []
    for a in anns:
        if a.notes:
            # Notes may be stored as a plain string or as a JSON list of strings.
            try:
                n = json.loads(a.notes)
                if isinstance(n, list):
                    user_notes.extend(str(x) for x in n if x is not None and str(x).strip())
                elif isinstance(n, str) and n.strip():
                    user_notes.append(n.strip())
            except json.JSONDecodeError:
                user_notes.append(a.notes)
        try:
            t = json.loads(a.tags or "[]")
            if isinstance(t, list):
                user_tags.extend(str(x) for x in t)
        except json.JSONDecodeError:
            pass
    fb_summary = _feedback_summary_for_image(db, im.id) if include_feedback_summary else None
    return ImageOut(
        id=im.id,
        file_path=im.file_path,
        designer=im.designer,
        captured_year=im.captured_year,
        captured_month=im.captured_month,
        captured_season=im.captured_season,
        ai_title=ai_title,
        description=im.description,
        ai_attributes=ai_attrs,
        ai_source=ai_source,
        user_tags=user_tags,
        user_notes=user_notes,
        feedback_summary=fb_summary,
        created_at=im.created_at,
    )


app.mount("/assets", StaticFiles(directory=str(STATIC_DIR / "assets")), name="assets")


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/filters", response_model=FilterOptions)
def api_filters(db: Session = Depends(get_db)) -> FilterOptions:
    data = collect_filter_options(db)
    return FilterOptions(**data)


@app.get("/api/images", response_model=list[ImageOut])
def api_list_images(
    db: Session = Depends(get_db),
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
) -> list[ImageOut]:
    rows = query_images(
        db,
        q=q,
        garment_type=garment_type,
        style=style,
        material=material,
        pattern=pattern,
        season=season,
        occasion=occasion,
        consumer_profile=consumer_profile,
        trend_notes=trend_notes,
        color_palette=color_palette,
        continent=continent,
        country=country,
        city=city,
        designer=designer,
        captured_year=captured_year,
        captured_month=captured_month,
        captured_season=captured_season,
    )
    return [_to_image_out(r, db, include_feedback_summary=False) for r in rows]


@app.get("/api/images/{image_id}", response_model=ImageOut)
def api_get_image(image_id: int, db: Session = Depends(get_db)) -> ImageOut:
    im = db.query(ImageRecord).filter(ImageRecord.id == image_id).one_or_none()
    if not im:
        raise HTTPException(status_code=404, detail="Not found")
    return _to_image_out(im, db, include_feedback_summary=True)


@app.post("/api/images", response_model=ImageOut)
async def api_upload_image(
    db: Session = Depends(get_db),
    file: UploadFile = File(...),
    designer: str | None = Form(None),
    captured_year: int | None = Form(None),
    captured_month: int | None = Form(None),
    captured_season: str | None = Form(None),
) -> ImageOut:
    if not file.content_type or not file.content_type.startswith("image/"):
        raise HTTPException(status_code=400, detail="Expected an image file")

    ext = Path(file.filename or "upload").suffix.lower()
    if ext not in (".jpg", ".jpeg", ".png", ".webp"):
        ext = ".jpg"
    fname = f"{uuid.uuid4().hex}{ext}"
    dest = UPLOAD_DIR / fname
    data = await file.read()
    dest.write_bytes(data)

    settings = get_settings()
    try:
        storage, raw = classify_image_bytes(settings, data, file.content_type)
    except Exception as e:
        detail = f"AI classification failed: {type(e).__name__}"
        if isinstance(e, httpx.HTTPStatusError):
            try:
                j = e.response.json()
                msg = j.get("error", {}).get("message")
                if msg:
                    detail = f"AI classification failed: {msg}"
            except Exception:
                pass
        else:
            msg = str(e).strip()
            if msg:
                detail = f"AI classification failed: {msg}"
        raise HTTPException(status_code=502, detail=detail) from e

    im = ImageRecord(
        file_path=f"/media/{fname}",
        designer=designer,
        captured_year=captured_year,
        captured_month=captured_month,
        captured_season=captured_season,
        description=storage.get("description"),
        ai_metadata_json=json.dumps(storage, ensure_ascii=False),
        raw_model_output=raw,
    )
    db.add(im)
    db.commit()
    db.refresh(im)
    return _to_image_out(im, db, include_feedback_summary=False)


@app.delete("/api/images/{image_id}")
def api_delete_image(image_id: int, db: Session = Depends(get_db)) -> dict[str, str]:
    im = db.query(ImageRecord).filter(ImageRecord.id == image_id).one_or_none()
    if not im:
        raise HTTPException(status_code=404, detail="Not found")

    fname = _filename_from_file_path(im.file_path)
    media_path = (UPLOAD_DIR / fname) if fname else None

    db.delete(im)
    db.commit()

    if media_path and media_path.is_file():
        try:
            media_path.unlink()
        except OSError:
            # DB delete succeeded; file delete best-effort
            pass
    return {"status": "deleted"}


@app.post("/api/images/{image_id}/annotations", response_model=ImageOut)
def api_add_annotation(
    image_id: int,
    body: AnnotationCreate,
    db: Session = Depends(get_db),
) -> ImageOut:
    im = db.query(ImageRecord).filter(ImageRecord.id == image_id).one_or_none()
    if not im:
        raise HTTPException(status_code=404, detail="Not found")
    ann = UserAnnotation(
        image_id=image_id,
        tags=json.dumps(body.tags, ensure_ascii=False),
        notes=body.notes,
    )
    db.add(ann)
    db.commit()
    db.refresh(im)
    return _to_image_out(im, db, include_feedback_summary=True)


@app.put("/api/images/{image_id}/annotations/state", response_model=ImageOut)
def api_set_annotation_state(
    image_id: int,
    body: AnnotationStateUpdate,
    db: Session = Depends(get_db),
) -> ImageOut:
    im = db.query(ImageRecord).filter(ImageRecord.id == image_id).one_or_none()
    if not im:
        raise HTTPException(status_code=404, detail="Not found")

    # Replace existing annotations with a single "current state" row.
    db.query(UserAnnotation).filter(UserAnnotation.image_id == image_id).delete()
    ann = UserAnnotation(
        image_id=image_id,
        tags=json.dumps(body.tags, ensure_ascii=False),
        notes=json.dumps(body.notes, ensure_ascii=False),
    )
    db.add(ann)
    db.commit()
    db.refresh(im)
    return _to_image_out(im, db, include_feedback_summary=True)


@app.put("/api/images/{image_id}/metadata", response_model=ImageOut)
def api_update_library_metadata(
    image_id: int,
    body: LibraryMetadataUpdate,
    db: Session = Depends(get_db),
) -> ImageOut:
    im = db.query(ImageRecord).filter(ImageRecord.id == image_id).one_or_none()
    if not im:
        raise HTTPException(status_code=404, detail="Not found")
    im.designer = body.designer
    im.captured_year = body.captured_year
    im.captured_month = body.captured_month
    im.captured_season = body.captured_season
    db.add(im)
    db.commit()
    db.refresh(im)
    return _to_image_out(im, db, include_feedback_summary=True)


@app.post("/api/images/{image_id}/feedback", response_model=FeedbackOut)
def api_add_feedback(
    image_id: int,
    body: FeedbackCreate,
    db: Session = Depends(get_db),
) -> FeedbackOut:
    im = db.query(ImageRecord).filter(ImageRecord.id == image_id).one_or_none()
    if not im:
        raise HTTPException(status_code=404, detail="Not found")
    settings = get_settings()
    corr_json = (
        json.dumps(body.corrected_attributes, ensure_ascii=False) if body.corrected_attributes else None
    )
    comment = body.comment.strip() if body.comment else None
    row = HumanFeedback(
        image_id=image_id,
        rating=body.rating,
        comment=comment or None,
        corrected_attributes_json=corr_json,
        ai_snapshot_json=im.ai_metadata_json,
        model_label=settings.openai_model,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return _to_feedback_out(row, include_ai_snapshot=False)


@app.get("/api/images/{image_id}/feedback", response_model=list[FeedbackOut])
def api_list_feedback(
    image_id: int,
    include_ai_snapshot: bool = False,
    db: Session = Depends(get_db),
) -> list[FeedbackOut]:
    im = db.query(ImageRecord).filter(ImageRecord.id == image_id).one_or_none()
    if not im:
        raise HTTPException(status_code=404, detail="Not found")
    rows = (
        db.query(HumanFeedback)
        .filter(HumanFeedback.image_id == image_id)
        .order_by(HumanFeedback.created_at.desc())
        .all()
    )
    return [_to_feedback_out(r, include_ai_snapshot=include_ai_snapshot) for r in rows]


@app.get("/media/{filename}")
def serve_media(filename: str) -> FileResponse:
    safe = _safe_filename(filename)
    path = UPLOAD_DIR / safe
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Not found")
    return FileResponse(path)


@app.get("/")
def root() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")
