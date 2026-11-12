# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).
While the version is 0.x, minor releases may contain breaking changes.

## [Unreleased]

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
