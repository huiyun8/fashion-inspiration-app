"""Pydantic schemas for API and AI-structured output."""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator


class LocationContext(BaseModel):
    continent: str | None = None
    country: str | None = None
    city: str | None = None


class StructuredGarmentAttributes(BaseModel):
    garment_type: str | None = None
    style: str | None = None
    material: str | None = None
    color_palette: list[str] = Field(default_factory=list)
    pattern: str | None = None
    season: str | None = None
    occasion: str | None = None
    consumer_profile: str | None = None
    trend_notes: str | None = None
    location: LocationContext = Field(default_factory=LocationContext)


class ClassificationResult(BaseModel):
    description: str
    attributes: StructuredGarmentAttributes


class AnnotationCreate(BaseModel):
    tags: list[str] = Field(default_factory=list)
    notes: str | None = None


class AnnotationStateUpdate(BaseModel):
    tags: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


class LibraryMetadataUpdate(BaseModel):
    designer: str | None = None
    captured_year: int | None = Field(None, ge=1900, le=2100)
    captured_month: int | None = Field(None, ge=1, le=12)
    captured_season: str | None = None


class FeedbackCreate(BaseModel):
    rating: int | None = Field(None, ge=1, le=5)
    comment: str | None = None
    corrected_attributes: dict[str, Any] | None = None

    @model_validator(mode="after")
    def non_empty(self):
        has_comment = bool(self.comment and self.comment.strip())
        has_corr = bool(self.corrected_attributes)
        if self.rating is None and not has_comment and not has_corr:
            raise ValueError("Provide at least one of: rating, comment, corrected_attributes")
        return self


class FeedbackSummary(BaseModel):
    count: int
    avg_rating: float | None = None


class FeedbackOut(BaseModel):
    id: int
    image_id: int
    rating: int | None
    comment: str | None
    corrected_attributes: dict[str, Any] | None = None
    model_label: str | None = None
    ai_snapshot: dict[str, Any] | None = None
    created_at: datetime


class ImageOut(BaseModel):
    id: int
    file_path: str
    designer: str | None
    captured_year: int | None
    captured_month: int | None
    captured_season: str | None
    ai_title: str | None = None
    description: str | None
    ai_attributes: dict[str, Any] | None = None
    ai_source: str = "unknown"
    user_tags: list[str] = Field(default_factory=list)
    user_notes: list[str] = Field(default_factory=list)
    feedback_summary: FeedbackSummary | None = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class FilterOptions(BaseModel):
    garment_type: list[str]
    style: list[str]
    material: list[str]
    pattern: list[str]
    season: list[str]
    occasion: list[str]
    consumer_profile: list[str]
    trend_notes: list[str]
    color_palette: list[str]
    continent: list[str]
    country: list[str]
    city: list[str]
    designer: list[str]
    captured_year: list[int]
    captured_month: list[int]
    captured_season: list[str]
