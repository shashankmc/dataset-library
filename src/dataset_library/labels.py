"""Whether a dataset has labels, from its own column types (eng review E2).

`yes`: a class-label column (or a list of them), or a summary or judgment
text column, which are what legal-ml-core trains on for those tasks.
`unclear`: a column that looks like a label but is plain text (`answer`,
`label` as a string...), or a dataset the viewer cannot read.
`no`: nothing label-like at all."""
import logging

from .errors import ProviderRateLimited
from .providers import viewer

log = logging.getLogger("dataset_library")

CACHE_SECONDS = 3600
TARGET_TEXT_COLUMNS = {"summary", "judgment"}
LABEL_LIKE = {"label", "labels", "answer", "answers", "gold", "class", "category", "target", "tags", "ner_tags",
              "outcome", "verdict", "entities"}


def is_class_label(feature):
    if isinstance(feature, list):
        return any(is_class_label(f) for f in feature)
    if not isinstance(feature, dict):
        return False
    if feature.get("_type") == "ClassLabel":
        return True
    # A sequence of class labels: {"_type": "Sequence", "feature": {...ClassLabel}}.
    return is_class_label(feature.get("feature"))


def of_features(features):
    """`yes`, `unclear` or `no` for one config's features."""
    names = {name.lower() for name in features}
    if any(is_class_label(feature) for feature in features.values()):
        return "yes"
    if names & TARGET_TEXT_COLUMNS:
        return "yes"
    if names & LABEL_LIKE:
        return "unclear"
    return "no"


def of_dataset(external_id):
    try:
        body = viewer.get("info", dataset=external_id)
    except viewer.ViewerUnavailable as exc:
        log.info("library.labels.unavailable dataset=%s error=%s", external_id, exc)
        return "unclear"
    configs = (body.get("dataset_info") or {}).values()
    verdicts = [of_features(config.get("features") or {}) for config in configs if isinstance(config, dict)]
    if "yes" in verdicts:
        return "yes"
    if "unclear" in verdicts or not verdicts:
        return "unclear"
    return "no"


def for_ids(cache, external_ids):
    """{external id: verdict}, each cached for an hour."""
    found = {}
    for external_id in external_ids:
        key = f"library:labels:{external_id}"
        verdict = cache.get(key)
        if verdict is None:
            try:
                verdict = of_dataset(external_id)
            except ProviderRateLimited:
                found[external_id] = "unclear"
                continue
            cache.set(key, verdict, CACHE_SECONDS)
        found[external_id] = verdict
    return found
