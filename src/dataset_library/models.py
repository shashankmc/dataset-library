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
