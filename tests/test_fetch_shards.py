"""Fetching a split's Parquet shards from Hugging Face (#113), from recorded listings."""
import json
import pathlib

import pytest

from dataset_library.errors import ProviderUnavailable
from dataset_library.imports import ImportFailed
from dataset_library.providers import parquet

LISTINGS = json.loads((pathlib.Path(__file__).parent / "fixtures" / "parquet" / "listings.json").read_text())
HUB = json.loads((pathlib.Path(__file__).parent / "fixtures" / "hub" / "datasets.json").read_text())
MB = 1_000_000


class Response:
    def __init__(self, status_code, body=None, content=b""):
        self.status_code = status_code
        self._body = body
        self._content = content

    def json(self):
        return self._body

    def iter_content(self, chunk_size):
        for i in range(0, len(self._content), chunk_size):
            yield self._content[i : i + chunk_size]

    def close(self):
        pass


class FakeHuggingFace:
    """The viewer's /parquet and the Hub from recordings; a shard's bytes are its
    name, so a test can tell which shards were downloaded."""

    def __init__(self):
        self.downloads = []
        self.failures = []  # statuses answered before the real one, per call

    def get(self, url, params=None, timeout=None, stream=False, **kwargs):
        if self.failures:
            return Response(self.failures.pop(0), {"error": "busy"})
        if url == parquet.LISTING:
            recorded = LISTINGS[f"{params['dataset']}?config={params['config']}"]
            return Response(recorded["status"], recorded["body"])
        if url.startswith(parquet.HUB):
            recorded = HUB.get(url.removeprefix(parquet.HUB), {"status": 404, "body": {"error": "Repository not found"}})
            return Response(recorded["status"], recorded["body"])
        assert stream, "shards are streamed"
        self.downloads.append(url)
        return Response(200, content=url.encode())


@pytest.fixture
def hf(monkeypatch):
    fake = FakeHuggingFace()
    monkeypatch.setattr(parquet.requests, "get", fake.get)
    return fake


def fetch(tmp_path, dataset, config, split, max_bytes=200 * MB):
    return parquet.fetch_shards(dataset, config, split, max_bytes, str(tmp_path / "work"), sleep=lambda s: None)


def test_only_the_chosen_splits_shards_are_downloaded_at_the_hubs_revision(hf, tmp_path):
    fetched = fetch(tmp_path, "coastalcph/lex_glue", "ledgar", "train")

    assert hf.downloads == ["https://huggingface.co/datasets/coastalcph/lex_glue/resolve/refs%2Fconvert%2Fparquet/ledgar/train/0000.parquet"]
    assert fetched.revision == "c23fdff1a6bf74e0e1a71cb86f1e781d37da888c"
    assert [pathlib.Path(p).read_bytes() for p in fetched.paths] == [hf.downloads[0].encode()]


def test_shards_are_downloaded_until_the_byte_cap(hf, tmp_path):
    # Shards of 198 MB, 228 MB, 236 MB, …: a 450 MB cap takes the first two.
    fetched = fetch(tmp_path, "isaacus/open-australian-legal-corpus", "corpus", "corpus", max_bytes=450 * MB)

    assert len(fetched.paths) == 2
    assert [u.rsplit("/", 1)[1] for u in hf.downloads] == ["0000.parquet", "0001.parquet"]


def test_a_first_shard_over_the_cap_is_too_large_to_sample(hf, tmp_path):
    with pytest.raises(ImportFailed) as refused:
        fetch(tmp_path, "isaacus/open-australian-legal-corpus", "corpus", "corpus", max_bytes=100 * MB)

    assert refused.value.code == "too_large"
    assert refused.value.message == "Too large to sample here: even one part of this dataset is over the download limit."
    assert hf.downloads == []


def test_a_dataset_the_viewer_cannot_convert_is_refused_plainly(hf, tmp_path):
    with pytest.raises(ImportFailed) as refused:
        fetch(tmp_path, "jfrenz/legalglue", "default", "train")

    assert refused.value.code == "not_importable"
    assert "Hugging Face cannot convert" in refused.value.message


def test_429_and_5xx_are_retried_three_times_then_hugging_face_is_busy(hf, tmp_path):
    hf.failures = [503, 429, 502]
    assert fetch(tmp_path, "coastalcph/lex_glue", "ledgar", "train").paths

    hf.failures = [503, 503, 503, 503]
    with pytest.raises(ProviderUnavailable):
        fetch(tmp_path, "coastalcph/lex_glue", "ledgar", "train")
