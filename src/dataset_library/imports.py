"""Importing a sample of a Hugging Face dataset as the host's own Dataset (#113).

    queued ─► fetching ─► sampling ─► validating ─► completed
       └──────────┴───────────┴────────────┴─► failed

The import row is the source of truth: the worker reads its status before
every step, and a terminal status never changes. The host supplies how shards
are fetched (``fetch_shards``) and how a file becomes a Dataset
(``create_dataset``, which raises ``ValueError`` with a student-readable
message for every refusal).
"""
import csv
import json
import logging
import os
import random
import shutil
from dataclasses import dataclass, field
from datetime import datetime, timezone

from sqlalchemy.exc import InvalidRequestError
from sqlalchemy.orm.exc import ObjectDeletedError

from .errors import ProviderError
from .models import LibraryImport

logger = logging.getLogger("dataset_library")

QUEUED, FETCHING, SAMPLING, VALIDATING = "queued", "fetching", "sampling", "validating"
COMPLETED, FAILED = "completed", "failed"
TERMINAL = {COMPLETED, FAILED, "cancelled"}

UNEXPECTED = "The import stopped on our side. Try again, and tell your course staff if it keeps happening."
BUSY = "Hugging Face is busy. Try again in a few minutes."
NOT_STARTED = "Import could not start. Try again."
CHANGED = "This dataset changed on Hugging Face after you opened it. Open it again to import the new version."
# How much of a dataset an import may download before it samples.
MAX_FETCH_BYTES = 200_000_000


@dataclass
class Fetched:
    """Downloaded Parquet shards of one split, at the revision they were read from."""

    paths: list = field(default_factory=list)
    revision: str | None = None


class ImportFailed(Exception):
    """A refusal the student can act on: `message` is shown as it is."""

    def __init__(self, code, message):
        super().__init__(message)
        self.code = code
        self.message = message


class Refused(Exception):
    """An import that cannot start; nothing was queued."""

    def __init__(self, status, code, message):
        super().__init__(message)
        self.status, self.code, self.message = status, code, message


def start(host, owner_id, body):
    """Check the request against the dataset as previewed, store the import as
    queued, then hand it to the host's queue. Returns the import as JSON."""
    from . import preview as preview_module
    from .providers.huggingface import DATASET_ID_PATTERN

    external_id = body.get("dataset")
    if not isinstance(external_id, str) or not DATASET_ID_PATTERN.match(external_id):
        raise Refused(400, "bad_id", "Pick a Hugging Face dataset to import.")
    task_type = body.get("taskType") or "classification"
    if task_type not in host.task_types:
        raise Refused(400, "bad_task", f"Unknown task type: {task_type}")
    name = body.get("name")
    name = name.strip() if isinstance(name, str) else ""
    if len(name) > 255:
        raise Refused(400, "bad_name", "Keep the name under 256 characters.")
    size = body.get("size")
    if isinstance(size, bool) or not isinstance(size, int) or size < 1:
        raise Refused(400, "bad_size", "Say how many rows to import, as a whole number above 0.")
    try:
        dataset = preview_module.preview(host, external_id, body.get("config") or None, body.get("split") or None)
    except preview_module.NotInLibrary:
        raise Refused(404, "not_found", "That dataset is not in the library.")
    except preview_module.UnknownConfig:
        raise Refused(400, "bad_config", "That dataset has no such configuration or split.")
    if dataset["gated"]:
        raise Refused(409, "gated", "Its owner only shares it with people signed in on Hugging Face, so it cannot be imported.")
    if dataset["preview"] != "ok":
        raise Refused(409, "not_importable", "Hugging Face cannot show this dataset's rows, so it cannot be imported.")
    columns = {c["name"] for c in dataset["columns"]}
    text_column, label_column = body.get("textColumn"), body.get("labelColumn") or None
    if text_column not in columns:
        raise Refused(400, "bad_mapping", "Pick the column that holds the text.")
    if label_column is not None and label_column not in columns:
        raise Refused(400, "bad_mapping", "Pick a label column from this dataset, or none.")
    if dataset["license"]["level"] == "warn" and body.get("licenseAck") is not True:
        raise Refused(409, "needs_ack", "Confirm the license terms to import this dataset.")

    session = host.db.session
    cap = host.max_rows()
    earlier = session.query(LibraryImport).filter_by(owner_id=owner_id, provider="huggingface", external_id=external_id).count()
    record = LibraryImport(
        owner_id=owner_id, provider="huggingface", external_id=external_id,
        config=dataset["config"], split=dataset["split"], revision=dataset.get("revision"), url=dataset["url"],
        license=dataset["license"]["id"], license_ack_at=_now() if body.get("licenseAck") is True else None,
        text_column=text_column, label_column=label_column, task_type=task_type,
        sample_size=min(size, cap), max_rows=cap,
        name=name or (dataset["title"] if not earlier else f"{dataset['title']} ({earlier + 1})"),
        status=QUEUED,
    )
    session.add(record)
    session.commit()
    _log(record, QUEUED, size=record.sample_size)
    try:
        host.enqueue(record.id)
    except Exception:  # noqa: BLE001 - whatever the queue raised, nothing will run it
        logger.exception(f"library.import.enqueue_failed import={record.id}")
        record.status, record.error_code, record.error_message = FAILED, "not_started", NOT_STARTED
        session.commit()
        raise Refused(503, "not_started", NOT_STARTED)
    return record.to_dict()


def get(host, owner_id, import_ref):
    record = host.db.session.get(LibraryImport, import_ref)
    return record.to_dict() if record is not None and record.owner_id == owner_id else None


def for_owner(host, owner_id):
    found = host.db.session.query(LibraryImport).filter_by(owner_id=owner_id).order_by(LibraryImport.created_at.desc())
    return [record.to_dict() for record in found]


class _Stopped(Exception):
    """The import reached a terminal status elsewhere (cancelled, say)."""


def _now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _log(record, state, **fields):
    extra = "".join(f" {k}={v}" for k, v in fields.items())
    logger.info(f"library.import.{state} import={record.id} dataset={record.external_id}{extra}")


def run_import(
    import_ref, *, session, fetch_shards, create_dataset, data_dir, max_bytes=MAX_FETCH_BYTES, seed=None, open_parquet=None
):
    """Drive one queued import to completed or failed. Safe to call twice."""
    record = session.get(LibraryImport, import_ref)
    if record is None or record.status != QUEUED:
        return
    work = os.path.join(data_dir, "library-imports", record.id)
    try:
        _advance(session, record, FETCHING)
        fetched = fetch_shards(record.external_id, record.config, record.split, max_bytes, work)
        if record.revision and fetched.revision and fetched.revision != record.revision:
            raise ImportFailed("changed", CHANGED)
        _advance(session, record, SAMPLING, {"revision": fetched.revision})
        rows = _sample(record, fetched.paths, random.Random(seed), open_parquet)
        _advance(session, record, VALIDATING)
        path = os.path.join(data_dir, f"library-{record.id}.csv")
        _write_csv(path, record, rows)
        try:
            dataset_ref = create_dataset(record.owner_id, path, record.name, _description(record), record.task_type)
        except ValueError as exc:
            os.remove(path)
            raise ImportFailed("invalid", str(exc)) from exc
        _advance(session, record, COMPLETED, {"dataset_ref": str(dataset_ref), "rows": len(rows), "imported_at": _now()})
    except _Stopped:
        pass
    except ImportFailed as exc:
        _fail(session, record, exc.code, exc.message)
    except ProviderError:
        _fail(session, record, "provider_busy", BUSY)
    except Exception:  # noqa: BLE001 - an import must end, whatever broke
        logger.exception(f"library.import.error import={record.id}")
        _fail(session, record, "unexpected", UNEXPECTED)
    finally:
        shutil.rmtree(work, ignore_errors=True)


def _check(session, record):
    """Stop when the import ended elsewhere, or its row is gone (account deletion)."""
    try:
        session.refresh(record)
    except (ObjectDeletedError, InvalidRequestError):
        raise _Stopped()
    if record.status in TERMINAL:
        raise _Stopped()


def _advance(session, record, state, updates=None):
    """Move to `state` unless the import already ended, saving `updates` with it."""
    _check(session, record)
    for name, value in (updates or {}).items():
        setattr(record, name, value)
    record.status = state
    session.commit()
    _log(record, state, **({"rows": record.rows} if state == COMPLETED else {}))


def _fail(session, record, code, message):
    session.rollback()
    try:
        _check(session, record)
    except _Stopped:
        return
    record.status, record.error_code, record.error_message = FAILED, code, message
    session.commit()
    _log(record, FAILED, code=code)


def _label_names(parquet_file, column):
    metadata = parquet_file.schema_arrow.metadata or {}
    try:
        features = json.loads(metadata[b"huggingface"])["info"]["features"]
    except (KeyError, ValueError, TypeError):
        return None
    feature = features.get(column) or {}
    return feature.get("names") if feature.get("_type") == "ClassLabel" else None


def _sample(record, paths, rng, open_parquet):
    """Pick `sample_size` rows with text, uniformly at random, reading as little as possible.

    Pass 1 reads only each row group's row count; pass 2 reads only the mapped
    columns of the row groups that hold a chosen row."""
    if open_parquet is None:
        import pyarrow.parquet as pq

        open_parquet = pq.ParquetFile
    files = [open_parquet(path) for path in paths]
    groups = []  # (file index, row group, first row, row count)
    total = 0
    for f_index, parquet_file in enumerate(files):
        metadata = parquet_file.metadata
        for g in range(metadata.num_row_groups):
            count = metadata.row_group(g).num_rows
            groups.append((f_index, g, total, count))
            total += count
    columns = [record.text_column] + ([record.label_column] if record.label_column else [])
    names = [_label_names(f, record.label_column) if record.label_column else None for f in files]

    want = min(record.sample_size, total)
    kept, seen = [], set()
    while len(kept) < want and len(seen) < total:
        batch = _draw(rng, total, seen, want - len(kept))
        for values, f_index in _read(files, groups, batch, columns):
            text = values[0]
            if text is None or not str(text).strip():
                continue
            kept.append((values, f_index))
    if not kept:
        raise ImportFailed("no_usable_rows", "None of the rows we read had any text, so there is nothing to import.")
    return [_mapped(values, names[f_index]) for values, f_index in kept[:want]]


def _draw(rng, total, seen, k):
    """`k` row numbers not drawn before."""
    left = total - len(seen)
    k = min(k, left)
    if len(seen) > total // 2:
        picked = rng.sample([i for i in range(total) if i not in seen], k)
    else:
        picked = set()
        while len(picked) < k:
            i = rng.randrange(total)
            if i not in seen:
                picked.add(i)
        picked = sorted(picked)
    seen.update(picked)
    return sorted(picked)


def _read(files, groups, rows, columns):
    """The chosen rows' mapped columns, one row group read at a time, with the
    row's file so its label names can be found."""
    out = []
    g_index = 0
    by_group = {}
    for row in rows:
        while not (groups[g_index][2] <= row < groups[g_index][2] + groups[g_index][3]):
            g_index += 1
        by_group.setdefault(g_index, []).append(row - groups[g_index][2])
    for g_index, offsets in by_group.items():
        f_index, g, _, _ = groups[g_index]
        table = files[f_index].read_row_group(g, columns=columns).to_pydict()
        for offset in offsets:
            out.append(([table[c][offset] for c in columns], f_index))
    return out


def _mapped(values, names):
    """A row as written for the host: text, then the label by name when it has one."""
    text = str(values[0])
    if len(values) == 1:
        return [text]
    label = values[1]
    if names and isinstance(label, int) and 0 <= label < len(names):
        label = names[label]
    return [text, "" if label is None else str(label)]


def _write_csv(path, record, rows):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    header = ["text", "label"] if record.label_column else ["text"]
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(header)
        writer.writerows(rows)


def _description(record):
    where = f"{record.config}/{record.split}" if record.config else record.split or ""
    return f"A random sample from Hugging Face: {record.external_id} {where}".strip()
