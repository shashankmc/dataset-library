"""Search across sources, with results cached and the license policy applied.

The cache holds the provider's cards before the policy, so an admin's change
applies at once. A fresh copy lasts ten minutes; the last good copy lasts a
day and is served, marked stale, while Hugging Face is limiting requests."""
import hashlib
import json
import logging
import time

from . import policy as policy_module
from .errors import ProviderRateLimited, ProviderUnavailable
from .licenses import LICENSES, UNKNOWN
from .models import LibrarySource
from .providers import huggingface

log = logging.getLogger("dataset_library")

FRESH_SECONDS = 600
LAST_GOOD_SECONDS = 86_400


def enabled_sources(db):
    return (
        db.session.query(LibrarySource)
        .filter_by(provider="huggingface", enabled=True)
        .order_by(LibrarySource.ref)
        .all()
    )


def search(host, *, query, task, license_id, source):
    """`source` must be one of the enabled sources' refs, or empty for all."""
    authors = [s.ref for s in enabled_sources(host.db)]
    if source:
        authors = [source]
    policy = policy_module.overrides(host.db)
    if license_id and policy.get(license_id) == "hide":
        return _body("ok", [])
    # The Hub has no tag for "no license", so those are picked out here.
    hub_license = None if license_id == "unknown" else license_id
    started = time.monotonic()
    key = _key(query, task, hub_license, authors)
    cards, status, cache_hit = host.cache.get(f"library:search:{key}"), "ok", True
    if cards is None:
        cache_hit = False
        try:
            cards = huggingface.search(query, task, hub_license, authors, host.task_types)
        except ProviderRateLimited:
            cards, status = host.cache.get(f"library:last:{key}"), "stale"
            if cards is None:
                cards, status = [], "unavailable"
        except ProviderUnavailable as exc:
            log.warning("library.search.provider_error provider=huggingface error=%s", exc)
            cards, status = [], "unavailable"
        else:
            host.cache.set(f"library:search:{key}", cards, FRESH_SECONDS)
            host.cache.set(f"library:last:{key}", cards, LAST_GOOD_SECONDS)
    results = _apply_policy(cards, policy, license_id)
    log.info(
        "library.search provider=huggingface query=%r task=%s license=%s status=%s results=%d cache_hit=%s ms=%d",
        query, task, license_id, status, len(results), cache_hit, (time.monotonic() - started) * 1000,
    )
    return _body(status, results)


def _apply_policy(cards, policy, license_id):
    results = []
    for card in cards:
        license = LICENSES.get(card["license"], UNKNOWN)
        if license_id == "unknown" and not license.unknown:
            continue
        card_level = policy_module.level(license, policy)
        if card_level == "hide":
            continue
        results.append({**card, "license": {**license.to_dict(), "level": card_level}})
    return results


def _key(*parts):
    return hashlib.sha256(json.dumps(parts, sort_keys=True).encode()).hexdigest()[:32]


def _body(status, results):
    return {"status": status, "results": results, "count": len(results)}
