"""The library's own tables. Hosts create them from LibraryBase.metadata or
from the package's migrations."""
import uuid
from datetime import datetime, timezone

from sqlalchemy import JSON, Boolean, DateTime, Integer, String, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def _now():
    # Naive UTC, as SQLite and most hosts store it.
    return datetime.now(timezone.utc).replace(tzinfo=None)


class LibraryBase(DeclarativeBase):
    pass


class LibrarySettings(LibraryBase):
    """One row: what an admin set. Missing values take the package defaults."""

    __tablename__ = "library_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    # {license id: "allow" | "warn" | "hide"}; a license not named keeps its default level.
    license_policy: Mapped[dict] = mapped_column(JSON, default=dict)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_now, onupdate=_now)


class LibrarySource(LibraryBase):
    """Where search looks: a Hugging Face organisation, for now."""

    __tablename__ = "library_sources"
    __table_args__ = (UniqueConstraint("provider", "ref", name="uq_library_sources_ref"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    provider: Mapped[str] = mapped_column(String(40))
    kind: Mapped[str] = mapped_column(String(20))  # "org"
    ref: Mapped[str] = mapped_column(String(200))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)

    def to_dict(self):
        return {"id": self.id, "provider": self.provider, "kind": self.kind, "ref": self.ref, "enabled": self.enabled}


class LibraryImport(LibraryBase):
    """One import of a sample, from queued to completed or failed. The database,
    not the queue, says where it is; a completed import is the dataset's provenance."""

    __tablename__ = "library_imports"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    owner_id: Mapped[str] = mapped_column(String(255), index=True)
    provider: Mapped[str] = mapped_column(String(40))
    external_id: Mapped[str] = mapped_column(String(200))
    config: Mapped[str | None] = mapped_column(String(200), nullable=True)
    split: Mapped[str | None] = mapped_column(String(200), nullable=True)
    revision: Mapped[str | None] = mapped_column(String(80), nullable=True)
    url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    license: Mapped[str] = mapped_column(String(80))
    license_ack_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    text_column: Mapped[str] = mapped_column(String(200))
    label_column: Mapped[str | None] = mapped_column(String(200), nullable=True)
    task_type: Mapped[str] = mapped_column(String(40))
    sample_size: Mapped[int] = mapped_column(Integer)
    # The row cap when the import was queued; a later change does not touch it.
    max_rows: Mapped[int] = mapped_column(Integer)
    name: Mapped[str] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(20), default="queued")
    error_code: Mapped[str | None] = mapped_column(String(40), nullable=True)
    error_message: Mapped[str | None] = mapped_column(String(500), nullable=True)
    dataset_ref: Mapped[str | None] = mapped_column(String(64), nullable=True)
    rows: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_now, onupdate=_now)
    imported_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    def to_dict(self):
        return {
            "id": self.id,
            "status": self.status,
            "error": self.error_message,
            "code": self.error_code,
            "provider": self.provider,
            "externalId": self.external_id,
            "config": self.config,
            "split": self.split,
            "revision": self.revision,
            "url": self.url,
            "license": self.license,
            "name": self.name,
            "taskType": self.task_type,
            "size": self.sample_size,
            "rows": self.rows,
            "datasetRef": self.dataset_ref,
            "createdAt": self.created_at.isoformat() + "Z" if self.created_at else None,
            "importedAt": self.imported_at.isoformat() + "Z" if self.imported_at else None,
        }
