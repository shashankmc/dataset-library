# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).
While the version is 0.x, minor releases may contain breaking changes.

## [Unreleased]

## [0.4.0] - 2026-11-12

### Added

- Import a random sample of a Hugging Face dataset as the host's own Dataset
  (BAIGLE #113). `init_dataset_library` takes `enqueue(import_ref)` and
  `max_rows()`; `/options` reports `importable` and `maxRows`.
  - `POST /api/library/imports` (an optional `name`; without one, the title,
    numbered on a repeat import), `GET /api/library/imports[/<ref>]`.
  - `dataset_library.imports.run_import` for the host's worker: queued →
    fetching → sampling → validating → completed, or failed; the database is the
    source of truth and is checked before every step.
  - `dataset_library.providers.parquet.fetch_shards`: the split's converted
    Parquet shards, downloaded up to a byte cap (200 MB by default), 429/5xx
    retried three times.
  - Two-pass sampling: row counts first, then only the mapped columns of the
    row groups holding a chosen row. Empty text is dropped; class labels are
    written by name.
  - The Hub revision seen at preview is pinned; a dataset changed since then
    is not imported. An import whose row is erased (account deletion) stops
    without making a dataset.
  - Table `library_imports` (migration `dl_0002_imports`).
- Cards carry `revision` (the Hub's commit sha).
- Optional extra `dataset-library[import]` (pyarrow, below 26 while hosts keep NumPy 1).

## [0.3.1] - 2026-11-12

### Fixed

- The preview route's parameter is `dataset_ref`, not `external_id`: BAIGLE
  refuses any `*_id` URL parameter that is not a UUID, so every preview there
  answered 404.

## [0.3.0] - 2026-11-12

### Added

- Library settings for admins (BAIGLE #118). `init_dataset_library` takes
  `is_admin()` (nobody by default) and `audit(event, **fields)`.
  - `GET /api/library/admin/settings`: the sources and every license with its
    default and current level.
  - `PUT /api/library/admin/settings` with `{"sources": [{"ref", "enabled"}],
    "license_policy": {id: level}}` replaces both. New sources must be Hugging
    Face organisations with public datasets. Any invalid field gives 400 with
    `fields` naming it, and nothing is saved. Each save is audited as
    `library.settings_saved` with counts and the license ids whose level changed.
  - `POST /api/library/admin/sources/check` with `{"ref"}` checks a source before saving.
  - `/options` reports `admin`.

## [0.2.1] - 2026-11-12

### Added

- The dataset preview's `rowCount`: the chosen split's size from the viewer's
  `/info`, or `null` when it does not say.

## [0.2.0] - 2026-11-12

### Added

- `GET /api/library/labels?ids=huggingface:org/name,...` (at most 30): whether
  each dataset has labels, `yes`, `no` or `unclear`, from its column types in
  Hugging Face's dataset viewer. A class-label column, or a summary or judgment
  column, is `yes`; a label-like text column, or a dataset the viewer cannot
  read, is `unclear`. Cached for an hour per dataset (BAIGLE #112).
- `GET /api/library/datasets/huggingface/<org>/<name>?config=&split=`: one
  dataset's card, configs and splits, column types and first 8 rows (class
  labels by name). `preview` is `unavailable` when the viewer cannot read the
  dataset or it is gated; the facts are still returned. 404 for a dataset
  outside the enabled sources or under a hidden license. Cached 10 minutes.

## [0.1.0] - 2026-11-12

### Added

- `init_dataset_library(app, *, db, login_required, current_owner, task_types, cache)`
  mounts the API under `/api/library`.
- `GET /api/library/search?q&task&license&source`: Hugging Face datasets as
  cards (title, tasks, license, size, gated, description), limited to the
  enabled sources. Cached for 10 minutes; the last good results are served as
  `stale` while the Hub limits requests, and `unavailable` when it is down.
- `GET /api/library/options`: the task, license and source filters, and the
  license table with this platform's levels.
- `resolve_license(tag)`: one license vocabulary, with flags and the condition
  and confirmation a student reads before importing.
- Tables `library_settings` and `library_sources`, with an Alembic revision
  (branch `dataset_library`).
