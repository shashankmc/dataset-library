# dataset-library

Search public legal datasets by **license** and **task** from a Flask app, and
import a random sample as the host's own Dataset. Built for
[BAIGLE](https://github.com/shashankmc/reducing_digital_divide), where law
students start with no data.

v0.1.0 searches the [Hugging Face Hub](https://huggingface.co/datasets).

## Installing into a host

```python
from dataset_library import init_dataset_library

init_dataset_library(
    app,
    db=db,                          # the host's Flask-SQLAlchemy handle
    login_required=jwt_required(),  # the host's sign-in decorator
    current_owner=get_jwt_identity,
    task_types=[t["value"] for t in TASK_TYPES],  # legal-ml-core's task types
    cache=RedisJSONCache(redis),    # get(key) / set(key, value, ttl)
    is_admin=lambda: "baigle-admin" in roles(),   # who may change the settings
    audit=lambda event, **fields: log(event, fields),
    enqueue=lambda ref: redis.lpush("library_import_queue", ref),  # no import without it
    max_rows=lambda: app.config["LEGAL_ML_MAX_ROWS"],             # read once per import
)
```

The worker that takes refs off that queue installs `dataset-library[import]`
(pyarrow) and runs each one, inside the host's app context:

```python
from dataset_library.imports import run_import
from dataset_library.providers.parquet import fetch_shards

run_import(ref, session=db.session, fetch_shards=fetch_shards,
           create_dataset=create, data_dir="/app/data")
```

`create(owner_id, file_path, name, description, task_type)` returns the new
dataset's id, or raises `ValueError` with a message a student can read
(legal-ml-core's `DatasetInvalid` is one).

Create the tables from `dataset_library.models.LibraryBase.metadata`, or add
`dataset_library/migrations/versions` to Alembic's `version_locations` (branch
label `dataset_library`).

## API

- `GET /api/library/search?q=&task=&license=&source=` →
  `{"status": "ok" | "stale" | "unavailable", "results": [...], "count": n}`.
  `stale`: the Hub is limiting requests and these are the last results, up to a
  day old. `unavailable`: the Hub is down or unreadable; nothing is raised.
- `GET /api/library/labels?ids=huggingface:org/name,...` → `{"labels": {id: "yes" | "no" | "unclear"}}`,
  from the dataset viewer's column types; up to 30 ids, cached an hour each.
- `GET /api/library/datasets/huggingface/<org>/<name>?config=&split=` → the
  card plus `configs`, `config`, `split`, `columns`, the first `rows`, `labels`
  `rowCount` (the split's size, when known) and `preview: "ok" | "unavailable"`.
- `GET /api/library/options` → the task, license and source filters, the
  license table (`level` is this platform's: `allow`, `warn` or `hide`),
  `importable` and `maxRows`.

- `POST /api/library/imports` with `{"dataset", "config", "split", "textColumn",
  "labelColumn", "size", "taskType"?, "licenseAck"?}` → 202 and the import,
  `queued`. The size is cut to `max_rows()`. Refused before anything is queued:
  400 (`bad_id`, `bad_mapping`, `bad_size`, `bad_task`, `bad_config`), 404, 409
  (`gated`, `not_importable`, `needs_ack` for a license set to warn), and 503
  when the queue is down (the import is stored as failed).
- `GET /api/library/imports` and `GET /api/library/imports/<ref>` → the
  signed-in user's imports: `status` (`queued`, `fetching`, `sampling`,
  `validating`, `completed`, `failed`), `error`, `rows`, `datasetRef`, and the
  provenance (`externalId`, `revision`, `url`, `license`, `importedAt`).
- Admins only (`is_admin()`): `GET` / `PUT /api/library/admin/settings` (sources
  and license levels, saved whole; 400 with `fields` when anything is invalid)
  and `POST /api/library/admin/sources/check` (`{"ref"}` → `{"ok", "error"?}`).

## Licenses

`dataset_library.licenses` is the one vocabulary. Each license has flags
(`nc`, `nd`, `sa`, `unknown`), a default level (`warn` for non-commercial,
no-derivatives and unknown licenses, `allow` otherwise), and for `warn` the
condition and the confirmation a student reads before importing. A license
tag nobody recognises resolves to `unknown`.

## Security

Only `https://huggingface.co` (the API and the converted Parquet files) and `https://datasets-server.huggingface.co` are called, with parameters built by
the package. Descriptions are returned as plain text for the host to escape.

## Development

```bash
python -m venv .venv && .venv/bin/pip install -e ".[test]"
.venv/bin/python -m pytest -q
```

Tests never call the Hub: `tests/fixtures/huggingface` holds recorded answers.

## License

MIT
