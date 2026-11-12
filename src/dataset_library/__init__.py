"""Search public legal datasets by license and task, and import a sample."""
from dataclasses import dataclass
from typing import Callable, Protocol

from .licenses import License, resolve_license

__version__ = "0.2.1"

__all__ = ["Cache", "License", "init_dataset_library", "resolve_license"]


class Cache(Protocol):
    """Where search results are kept for a while (Redis in BAIGLE)."""

    def get(self, key: str): ...

    def set(self, key: str, value, ttl: int) -> None: ...


@dataclass
class _Host:
    db: object
    login_required: Callable
    current_owner: Callable[[], str]
    task_types: list
    cache: Cache


def init_dataset_library(app, *, db, login_required, current_owner, task_types, cache, url_prefix="/api/library"):
    """Mount the library API on a host Flask app.

    ``db`` is the host's Flask-SQLAlchemy handle; the tables come from
    ``dataset_library.models.LibraryBase.metadata`` or the package's
    migrations. ``login_required`` is the host's sign-in decorator, applied to
    every route; ``current_owner`` returns the signed-in user's id.
    ``task_types`` are the host's task type ids (legal-ml-core's TASK_TYPES
    values): the library offers no other. ``cache`` keeps search results
    (``get(key)``, ``set(key, value, ttl)``, JSON-serialisable values).
    """
    from .routes import library_bp

    app.extensions["dataset_library"] = _Host(
        db=db,
        login_required=login_required,
        current_owner=current_owner,
        task_types=list(task_types),
        cache=cache,
    )
    app.register_blueprint(library_bp, url_prefix=url_prefix)
