"""Downloading one split's Parquet shards from Hugging Face, for an import (#113).

The viewer lists the shards it converted (``/parquet``); they are downloaded in
order, streamed, until the next would pass the byte cap. Only huggingface.co
and datasets-server.huggingface.co are called. 429 and 5xx are retried three
times with backoff, then the provider is unavailable."""
import os
import time

import requests

from ..errors import ProviderUnavailable
from ..imports import Fetched, ImportFailed

LISTING = "https://datasets-server.huggingface.co/parquet"
HUB = "https://huggingface.co/api/datasets/"
TIMEOUT = 30
RETRIES = 3
# Worth asking again; 501 is the viewer saying it cannot read the dataset at all.
RETRY_STATUSES = {429, 500, 502, 503, 504}
CHUNK = 1 << 20


def _get(url, sleep, **kwargs):
    for attempt in range(RETRIES + 1):
        try:
            response = requests.get(url, timeout=TIMEOUT, **kwargs)
        except requests.RequestException as exc:
            error = exc
        else:
            if response.status_code not in RETRY_STATUSES:
                return response
            error = f"answered {response.status_code}"
            response.close()
        if attempt < RETRIES:
            sleep(2**attempt)
    raise ProviderUnavailable(f"Hugging Face {error} after {RETRIES} retries")


def fetch_shards(external_id, config, split, max_bytes, dest_dir, *, sleep=time.sleep):
    listing = _get(LISTING, sleep, params={"dataset": external_id, "config": config})
    if listing.status_code != 200:
        raise ImportFailed(
            "not_importable",
            "Hugging Face cannot convert this dataset to files we can read, so it cannot be imported.",
        )
    shards = [s for s in listing.json().get("parquet_files") or [] if s.get("config") == config and s.get("split") == split]
    if not shards:
        raise ImportFailed("not_importable", "Hugging Face has no files for this part of the dataset.")

    chosen, total = [], 0
    for shard in shards:
        if total + shard["size"] > max_bytes:
            break
        chosen.append(shard)
        total += shard["size"]
    if not chosen:
        raise ImportFailed("too_large", "Too large to sample here: even one part of this dataset is over the download limit.")

    hub = _get(HUB + external_id, sleep)
    revision = hub.json().get("sha") if hub.status_code == 200 else None

    os.makedirs(dest_dir, exist_ok=True)
    paths = []
    for n, shard in enumerate(chosen):
        path = os.path.join(dest_dir, f"{n:05}.parquet")
        _download(shard["url"], path, shard["size"], sleep)
        paths.append(path)
    return Fetched(paths=paths, revision=revision)


def _download(url, path, expected, sleep):
    response = _get(url, sleep, stream=True)
    if response.status_code != 200:
        raise ProviderUnavailable(f"Hugging Face answered {response.status_code} for a shard")
    written = 0
    with open(path, "wb") as f:
        for chunk in response.iter_content(CHUNK):
            written += len(chunk)
            # A shard larger than listed is not trusted past a small margin.
            if written > expected * 1.1 + CHUNK:
                raise ImportFailed("too_large", "Too large to sample here: a part of this dataset is bigger than Hugging Face said.")
            f.write(chunk)
