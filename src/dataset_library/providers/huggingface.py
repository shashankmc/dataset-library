"""Search the Hugging Face Hub's dataset API.

Only https://huggingface.co is ever called, with parameters built here, never
a user-supplied URL."""
import re

import requests

from ..errors import ProviderRateLimited, ProviderUnavailable
from ..licenses import resolve_license
from ..tasks import hugging_face_filter, hugging_face_tasks

API = "https://huggingface.co/api/datasets"
DATASET_URL = "https://huggingface.co/datasets/{}"
TIMEOUT = 10
LIMIT = 30
# Organisation, or organisation/dataset.
ID_PATTERN = re.compile(r"^[\w.-]+(/[\w.-]+)?$")
# A dataset: organisation/dataset, no dots alone, nothing that walks a path.
DATASET_ID_PATTERN = re.compile(r"^(?!\.)[\w.-]+/(?!\.)[\w.-]+$")
SIZE = {"n<1K": (0, 1_000)}
_SUFFIX = {"K": 1_000, "M": 1_000_000, "B": 1_000_000_000, "T": 1_000_000_000_000}


def search(query, task, license_id, authors, task_types):
    """Matching datasets as library cards. `authors` limits the search to those
    organisations (one Hub call each); empty searches the whole Hub."""
    params = {"limit": LIMIT, "full": "true", "sort": "downloads"}
    if query:
        params["search"] = query
    filters = []
    if task:
        tag = hugging_face_filter(task)
        if tag is None:
            return []
        filters.append(tag)
    if license_id:
        filters.append(f"license:{license_id}")
    if filters:
        params["filter"] = filters
    records = []
    for author in authors or [None]:
        records.extend(_get_with_retry({**params, "author": author} if author else params))
    return [_card(record, task_types) for record in records if not record.get("private") and not record.get("disabled")]


# A source: one organisation's name.
ORGANISATION_PATTERN = re.compile(r"^(?!\.)[\w.-]{1,96}$")


def organisation_has_datasets(name):
    """Whether the Hub lists any public dataset from this organisation."""
    return bool(_get_with_retry({"author": name, "limit": 1}))


def dataset(external_id, task_types):
    """One dataset's card, or None when the Hub does not know it."""
    try:
        response = requests.get(f"{API}/{external_id}", timeout=TIMEOUT)
    except requests.RequestException as exc:
        raise ProviderUnavailable(str(exc)) from exc
    if response.status_code in (401, 404):
        return None
    if response.status_code == 429:
        raise ProviderRateLimited("Hugging Face is limiting requests")
    if response.status_code != 200:
        raise ProviderUnavailable(f"Hugging Face answered {response.status_code}")
    try:
        record = response.json()
    except ValueError as exc:
        raise ProviderUnavailable("Unreadable answer") from exc
    if not isinstance(record, dict) or record.get("private") or record.get("disabled"):
        return None
    return _card(record, task_types)


def _get_with_retry(params):
    """One retry when the Hub is down; none when it is limiting requests."""
    try:
        return _get(params)
    except ProviderRateLimited:
        raise
    except ProviderUnavailable:
        return _get(params)


def _get(params):
    try:
        response = requests.get(API, params=params, timeout=TIMEOUT)
    except requests.RequestException as exc:
        raise ProviderUnavailable(str(exc)) from exc
    if response.status_code == 429:
        raise ProviderRateLimited("Hugging Face is limiting requests")
    if response.status_code != 200:
        raise ProviderUnavailable(f"Hugging Face answered {response.status_code}")
    try:
        body = response.json()
    except ValueError as exc:
        raise ProviderUnavailable(f"Unreadable answer: {response.text[:200]}") from exc
    if not isinstance(body, list):
        raise ProviderUnavailable(f"Unexpected answer: {response.text[:200]}")
    return body


def _card(record, task_types):
    external_id = record["id"]
    tags = record.get("tags") or []
    card_data = record.get("cardData") or {}
    license_tag = next((t for t in tags if t.startswith("license:")), None) or _first(card_data.get("license"))
    return {
        "id": f"huggingface:{external_id}",
        "provider": "huggingface",
        "externalId": external_id,
        "author": external_id.split("/")[0],
        "title": _title(card_data.get("pretty_name"), external_id),
        "url": DATASET_URL.format(external_id),
        "tasks": hugging_face_tasks(tags, task_types),
        "license": resolve_license(license_tag).id,
        "size": _size(tags),
        "gated": bool(record.get("gated")),
        "description": _description(record.get("description")),
        "updated": (record.get("lastModified") or "")[:10] or None,
        "revision": record.get("sha"),
        "downloads": record.get("downloads") or 0,
    }


def _first(value):
    return value[0] if isinstance(value, list) and value else value if isinstance(value, str) else None


def _title(pretty_name, external_id):
    if isinstance(pretty_name, str) and pretty_name.strip():
        return pretty_name.strip()
    return external_id.split("/")[-1]


def _number(text):
    text = text.strip()
    if text and text[-1] in _SUFFIX:
        return int(float(text[:-1]) * _SUFFIX[text[-1]])
    return int(text)


def _size(tags):
    """`size_categories:100K<n<1M` as {"label": "100K–1M rows", "min", "max"}."""
    tag = next((t.removeprefix("size_categories:") for t in tags if t.startswith("size_categories:")), None)
    if not tag:
        return None
    if tag == "n<1K":
        return {"label": "under 1K rows", "min": 0, "max": 1_000}
    if tag.startswith("n>"):
        return {"label": f"over {tag[2:]} rows", "min": _number(tag[2:]), "max": None}
    low, _, high = tag.partition("<n<")
    try:
        return {"label": f"{low}–{high} rows", "min": _number(low), "max": _number(high)}
    except ValueError:
        return None


def _description(text, limit=300):
    """The card's summary as plain text: whitespace collapsed, the Hub's
    "Dataset Card for X / Dataset Summary" headings dropped, cut at a word."""
    text = " ".join((text or "").split())
    text = re.sub(r"^Dataset Card for .*? Dataset Summary ", "", text)
    text = re.sub(r"^Dataset Card for \S+\s*", "", text)
    if len(text) <= limit:
        return text
    return text[: limit - 1].rsplit(" ", 1)[0] + "…"
