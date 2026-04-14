from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class ImageRecord(Base):
    __tablename__ = "images"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    file_path: Mapped[str] = mapped_column(String(512), nullable=False)
    designer: Mapped[str | None] = mapped_column(String(256), nullable=True)
    captured_year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    captured_month: Mapped[int | None] = mapped_column(Integer, nullable=True)
    captured_season: Mapped[str | None] = mapped_column(String(64), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    ai_metadata_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    raw_model_output: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    annotations: Mapped[list["UserAnnotation"]] = relationship(
        "UserAnnotation", back_populates="image", cascade="all, delete-orphan"
    )
    feedback: Mapped[list["HumanFeedback"]] = relationship(
        "HumanFeedback", back_populates="image", cascade="all, delete-orphan"
    )


class UserAnnotation(Base):
    __tablename__ = "user_annotations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    image_id: Mapped[int] = mapped_column(ForeignKey("images.id", ondelete="CASCADE"), nullable=False)
    tags: Mapped[str] = mapped_column(Text, default="[]")
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    image: Mapped["ImageRecord"] = relationship("ImageRecord", back_populates="annotations")


class HumanFeedback(Base):
    __tablename__ = "human_feedback"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    image_id: Mapped[int] = mapped_column(ForeignKey("images.id", ondelete="CASCADE"), nullable=False)
    rating: Mapped[int | None] = mapped_column(Integer, nullable=True)
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    corrected_attributes_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    ai_snapshot_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    model_label: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    image: Mapped["ImageRecord"] = relationship("ImageRecord", back_populates="feedback")
