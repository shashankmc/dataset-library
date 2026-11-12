"""Importing a sample of a Hugging Face dataset (#113): the worker's side.

Shards are small Parquet files written here; `create_dataset` is a fake that
keeps what it was given, as the host's would store it.
"""
import csv
import json

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from dataset_library import imports
from dataset_library.models import LibraryImport

LABELS = ["Terminations", "Governing Laws", "Notices"]


def write_shard(path, texts, labels, row_group_size=None):
    """A Parquet shard as Hugging Face writes one: features in the schema metadata."""
    features = {
        "text": {"dtype": "string", "_type": "Value"},
        "label": {"names": LABELS, "_type": "ClassLabel"},
        "extra": {"dtype": "string", "_type": "Value"},
    }
    table = pa.table({"text": texts, "label": labels, "extra": ["x"] * len(texts)})
    table = table.replace_schema_metadata({"huggingface": json.dumps({"info": {"features": features}})})
    pq.write_table(table, path, row_group_size=row_group_size)
    return path


class FakeCreateDataset:
    def __init__(self, refuse=None):
        self.calls = []
        self.refuse = refuse

    def __call__(self, owner_id, file_path, name, description, task_type):
        with open(file_path, newline="") as f:
            rows = list(csv.DictReader(f))
        self.calls.append({"owner": owner_id, "name": name, "description": description, "task_type": task_type, "rows": rows})
        if self.refuse:
            raise ValueError(self.refuse)
        return "dataset-1"


@pytest.fixture
def run(app, tmp_path):
    """Queue an import directly and run it, as the host's worker would."""

    def go(shards, *, size=4, fail_fetch=None, refuse=None, open_parquet=None, **fields):
        create = FakeCreateDataset(refuse)

        def fetch_shards(external_id, config, split, max_bytes, dest_dir):
            create.fetched_with = (external_id, config, split, max_bytes)
            if fail_fetch:
                raise fail_fetch
            return imports.Fetched(paths=[str(p) for p in shards], revision="abc123")

        with app.app_context():
            session = app.db.session
            record = LibraryImport(
                owner_id="alice", provider="huggingface", external_id="coastalcph/lex_glue",
                config="ledgar", split="train", text_column="text", label_column="label",
                task_type="classification", sample_size=size, max_rows=1000, name="LexGLUE",
                license="cc-by-4.0", url="https://huggingface.co/datasets/coastalcph/lex_glue",
                **fields,
            )
            session.add(record)
            session.commit()
            imports.run_import(
                record.id, session=session, fetch_shards=fetch_shards,
                create_dataset=create, data_dir=str(tmp_path / "data"), seed=7, open_parquet=open_parquet,
            )
            session.refresh(record)
            return record.to_dict(), create

    return go


def test_an_import_samples_the_asked_number_of_rows_with_label_names(run, tmp_path):
    texts = [f"Clause {i}" for i in range(10)]
    shard = write_shard(tmp_path / "0000.parquet", texts, [i % 3 for i in range(10)])

    result, create = run([shard], size=4)

    assert result["status"] == "completed", result
    assert result["datasetRef"] == "dataset-1"
    assert result["rows"] == 4
    assert result["revision"] == "abc123"
    assert create.fetched_with == ("coastalcph/lex_glue", "ledgar", "train", 200_000_000)
    [call] = create.calls
    assert call["task_type"] == "classification"
    assert call["name"] == "LexGLUE"
    assert len(call["rows"]) == 4
    assert list(call["rows"][0]) == ["text", "label"]
    by_text = {t: LABELS[i % 3] for i, t in enumerate(texts)}
    for row in call["rows"]:
        assert row["label"] == by_text[row["text"]]


class SpyParquet:
    """A ParquetFile that records what is read: metadata, or which row groups and columns."""

    reads = []

    def __init__(self, path):
        self._file = pq.ParquetFile(path)
        self.path = str(path)

    @property
    def metadata(self):
        return self._file.metadata

    @property
    def schema_arrow(self):
        return self._file.schema_arrow

    def read_row_group(self, i, columns=None):
        SpyParquet.reads.append((self.path, i, tuple(columns or ())))
        return self._file.read_row_group(i, columns=columns)

    def __getattr__(self, name):
        raise AssertionError(f"read more than row counts and chosen row groups: {name}")


def test_pass_one_reads_row_counts_and_pass_two_only_the_mapped_columns_of_chosen_row_groups(run, tmp_path):
    shards = [
        write_shard(tmp_path / f"{n:04}.parquet", [f"Shard {n} clause {i}" for i in range(100)], [i % 3 for i in range(100)], row_group_size=10)
        for n in range(2)
    ]
    SpyParquet.reads = []

    result, create = run(shards, size=3, open_parquet=SpyParquet)

    assert result["status"] == "completed", result
    assert len(create.calls[0]["rows"]) == 3
    assert 1 <= len(SpyParquet.reads) <= 3
    assert all(columns == ("text", "label") for _, _, columns in SpyParquet.reads)
    # Each row group read holds one of the chosen rows.
    chosen = {row["text"] for row in create.calls[0]["rows"]}
    for path, group, _ in SpyParquet.reads:
        shard = path.rsplit("/", 1)[1][:4]
        assert any(t.startswith(f"Shard {int(shard)} clause ") and int(t.rsplit(" ", 1)[1]) // 10 == group for t in chosen)


def test_rows_with_empty_text_are_dropped_and_the_sample_stays_exact(run, tmp_path):
    texts = ["", "  ", None, "Kept one", "Kept two", "Kept three", "", "Kept four"]
    shard = write_shard(tmp_path / "0000.parquet", texts, [0] * len(texts))

    result, create = run([shard], size=4)

    assert result["status"] == "completed", result
    assert sorted(r["text"] for r in create.calls[0]["rows"]) == ["Kept four", "Kept one", "Kept three", "Kept two"]


def test_with_no_text_left_the_import_fails_and_no_dataset_is_made(run, tmp_path):
    shard = write_shard(tmp_path / "0000.parquet", ["", " ", None], [0, 1, 2])

    result, create = run([shard], size=2)

    assert result["status"] == "failed"
    assert result["code"] == "no_usable_rows"
    assert "nothing to import" in result["error"]
    assert create.calls == []


def test_a_refusal_from_create_dataset_is_shown_as_the_upload_would_show_it(run, tmp_path):
    shard = write_shard(tmp_path / "0000.parquet", ["A clause", "Another"], [0, 1])

    result, _ = run([shard], size=2, refuse="Classification needs at least 2 examples of each label")

    assert result["status"] == "failed"
    assert result["error"] == "Classification needs at least 2 examples of each label"
    assert not list((tmp_path / "data").glob("library-*.csv"))


def test_hugging_face_busy_after_retries_fails_with_a_plain_reason(run, tmp_path):
    from dataset_library.errors import ProviderUnavailable

    result, create = run([], fail_fetch=ProviderUnavailable("503 three times"))

    assert result["status"] == "failed"
    assert result["code"] == "provider_busy"
    assert result["error"] == "Hugging Face is busy. Try again in a few minutes."
    assert create.calls == []


def test_a_finished_import_is_not_run_again(run, tmp_path, app):
    shard = write_shard(tmp_path / "0000.parquet", ["A clause", "Another"], [0, 1])
    result, create = run([shard], size=2, status="failed")

    assert result["status"] == "failed"
    assert create.calls == []


def test_a_dataset_changed_since_its_preview_is_not_imported_unseen(run, tmp_path):
    shard = write_shard(tmp_path / "0000.parquet", ["A clause", "Another"], [0, 1])

    result, create = run([shard], size=2, revision="seen-at-preview")

    assert result["status"] == "failed"
    assert result["code"] == "changed"
    assert result["error"] == "This dataset changed on Hugging Face after you opened it. Open it again to import the new version."
    assert create.calls == []
