# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).
While the version is 0.x, minor releases may contain breaking changes.

## [Unreleased]

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
