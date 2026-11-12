"""Search public legal datasets by license and task, and import a sample."""
from dataclasses import dataclass
from typing import Callable, Protocol

from .licenses import License, resolve_license

__version__ = "0.4.0"

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
    is_admin: Callable[[], bool]
    audit: Callable[..., None]
    enqueue: Callable[[str], None] | None = None
    max_rows: Callable[[], int] = lambda: 1000


def init_dataset_library(
    app,
    *,
    db,
    login_required,
    current_owner,
    task_types,
    cache,
    is_admin=None,
    audit=None,
    enqueue=None,
    max_rows=None,
    url_prefix="/api/library",
):
    """Mount the library API on a host Flask app.

    ``db`` is the host's Flask-SQLAlchemy handle; the tables come from
    ``dataset_library.models.LibraryBase.metadata`` or the package's
    migrations. ``login_required`` is the host's sign-in decorator, applied to
    every route; ``current_owner`` returns the signed-in user's id.
    ``task_types`` are the host's task type ids (legal-ml-core's TASK_TYPES
    values): the library offers no other. ``cache`` keeps search results
    (``get(key)``, ``set(key, value, ttl)``, JSON-serialisable values).
    ``is_admin()`` says whether the signed-in user may change the library's
    settings (nobody, by default). ``audit(event, **fields)`` records each
    settings change; fields are counts and license ids, never personal data.
    ``enqueue(import_ref)`` hands a queued import to the host's worker, which
    calls ``dataset_library.imports.run_import``; without it there is no
    import. ``max_rows()`` is the most rows a dataset may have (legal-ml-core's
    LEGAL_ML_MAX_ROWS), read once when an import is queued.
    """
    from .routes import library_bp

    app.extensions["dataset_library"] = _Host(
        db=db,
        login_required=login_required,
        current_owner=current_owner,
        task_types=list(task_types),
        cache=cache,
        is_admin=is_admin or (lambda: False),
        audit=audit or (lambda event, **fields: None),
        enqueue=enqueue,
        max_rows=max_rows or (lambda: 1000),
    )
    app.register_blueprint(library_bp, url_prefix=url_prefix)
