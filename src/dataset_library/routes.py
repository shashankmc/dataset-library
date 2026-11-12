"""The HTTP API, under /api/library."""
from flask import Blueprint, current_app, jsonify, request

from . import admin as admin_module
from . import imports as imports_module
from . import labels as labels_module
from . import policy as policy_module
from . import preview as preview_module
from .errors import ProviderRateLimited, ProviderUnavailable
from . import search as search_module
from .licenses import GROUPS, LICENSES
from .providers.huggingface import DATASET_ID_PATTERN
from .tasks import hugging_face_filter

library_bp = Blueprint("dataset_library", __name__)


class ApiError(Exception):
    def __init__(self, status, message, code, **extra):
        super().__init__(message)
        self.status = status
        self.body = {"error": message, "code": code, **extra}


@library_bp.errorhandler(ApiError)
def _api_error(error):
    return jsonify(error.body), error.status


def _host():
    return current_app.extensions["dataset_library"]


@library_bp.before_request
def _sign_in():
    """The host's sign-in decorator around nothing: a refusal it returns or
    raises ends the request before any route runs."""
    return _host().login_required(lambda: None)()


@library_bp.route("/search", methods=["GET"])
def search():
    args = request.args
    task, license_id = args.get("task", "").strip(), args.get("license", "").strip()
    if task and task not in _host().task_types:
        raise ApiError(400, f"Unknown task type: {task}", "bad_filter")
    if license_id and license_id not in LICENSES:
        raise ApiError(400, f"Unknown license: {license_id}", "bad_filter")
    source = args.get("source", "").strip()
    if source and source not in {s.ref for s in search_module.enabled_sources(_host().db)}:
        raise ApiError(400, f"Not a library source: {source}", "bad_filter")
    return jsonify(
        search_module.search(
            _host(),
            query=args.get("q", "").strip(),
            task=task,
            license_id=license_id,
            source=source,
        )
    )


# What the host UI needs to label tasks; legal-ml-core's TASK_TYPES labels.
TASK_LABELS = {"classification": "Classification", "ner": "Named entities", "summarization": "Summarization"}


@library_bp.route("/options", methods=["GET"])
def options():
    """The filter choices, and the license table with this platform's levels."""
    host = _host()
    policy = policy_module.overrides(host.db)
    licenses = []
    for license in LICENSES.values():
        level = policy_module.level(license, policy)
        if level != "hide":
            licenses.append({**license.to_dict(), "level": level})
    return jsonify(
        {
            "tasks": [
                {"value": task, "label": TASK_LABELS.get(task, task)}
                for task in host.task_types
                if hugging_face_filter(task)
            ],
            "licenses": licenses,
            "groups": GROUPS,
            "admin": bool(host.is_admin()),
            "importable": host.enqueue is not None,
            "maxRows": host.max_rows(),
            "sources": [
                {"value": s.ref, "label": s.ref, "provider": s.provider}
                for s in search_module.enabled_sources(host.db)
            ],
        }
    )


MAX_LABEL_IDS = 30


def _hugging_face_ids(ids):
    """External ids from `huggingface:org/name` ids, refusing anything else."""
    external = []
    for library_id in ids:
        provider, _, external_id = library_id.partition(":")
        if provider != "huggingface" or not DATASET_ID_PATTERN.match(external_id):
            raise ApiError(400, f"Not a library dataset id: {library_id}", "bad_id")
        external.append(external_id)
    return external


@library_bp.route("/labels", methods=["GET"])
def labels():
    """Whether each dataset has labels: `yes`, `no` or `unclear`. The page
    asks for the cards it shows, so a search does not wait for this."""
    ids = [i for i in request.args.get("ids", "").split(",") if i]
    if len(ids) > MAX_LABEL_IDS:
        raise ApiError(400, f"At most {MAX_LABEL_IDS} ids at a time.", "too_many_ids")
    found = labels_module.for_ids(_host().cache, _hugging_face_ids(ids))
    return jsonify({"labels": {f"huggingface:{external_id}": verdict for external_id, verdict in found.items()}})


# The parameter is not called `*_id`: hosts may treat such URL parameters as
# their own database ids (BAIGLE refuses any that is not a UUID).
@library_bp.route("/datasets/huggingface/<path:dataset_ref>", methods=["GET"])
def dataset(dataset_ref):
    """One dataset's facts, configs and first rows (`?config=&split=`)."""
    if not DATASET_ID_PATTERN.match(dataset_ref):
        raise ApiError(400, f"Not a Hugging Face dataset id: {dataset_ref}", "bad_id")
    try:
        return jsonify(
            preview_module.preview(
                _host(), dataset_ref, request.args.get("config") or None, request.args.get("split") or None
            )
        )
    except preview_module.NotInLibrary:
        raise ApiError(404, "That dataset is not in the library.", "not_found")
    except preview_module.UnknownConfig:
        raise ApiError(400, "That dataset has no such configuration or split.", "bad_config")
    except ProviderRateLimited:
        raise ApiError(503, "Hugging Face is limiting requests. Try again in a few minutes.", "provider_rate_limited")
    except ProviderUnavailable:
        raise ApiError(503, "Hugging Face is unavailable right now. Try again in a few minutes.", "provider_unavailable")


def _require_admin():
    if not _host().is_admin():
        raise ApiError(403, "Only the course's library admins can change these settings.", "not_admin")


@library_bp.route("/admin/settings", methods=["GET"])
def get_settings():
    _require_admin()
    return jsonify({**admin_module.current(_host().db), "groups": GROUPS})


@library_bp.route("/admin/settings", methods=["PUT"])
def put_settings():
    _require_admin()
    host = _host()
    try:
        changes = admin_module.save(host.db, request.get_json(silent=True) or {})
    except admin_module.Invalid as invalid:
        host.db.session.rollback()
        raise ApiError(400, "Some settings need fixing.", "invalid", fields=invalid.fields)
    except (ProviderRateLimited, ProviderUnavailable):
        host.db.session.rollback()
        raise ApiError(503, "Hugging Face could not check the new sources. Try again in a few minutes.", "provider_unavailable")
    host.audit("library.settings_saved", **changes)
    return jsonify({**admin_module.current(host.db), "groups": GROUPS})


@library_bp.route("/admin/sources/check", methods=["POST"])
def check_source():
    """Whether a source can be added, before the admin saves."""
    _require_admin()
    ref = ((request.get_json(silent=True) or {}).get("ref") or "").strip()
    try:
        problem = admin_module.check_source(ref)
    except (ProviderRateLimited, ProviderUnavailable):
        raise ApiError(503, "Hugging Face could not be reached to check that. Try again in a few minutes.", "provider_unavailable")
    return jsonify({"ref": ref, "ok": True} if problem is None else {"ref": ref, "ok": False, "error": problem})


def _importing():
    if _host().enqueue is None:
        raise ApiError(404, "Importing is not offered here.", "not_found")


@library_bp.route("/imports", methods=["POST"])
def start_import():
    """Queue an import of a random sample; the worker does the rest."""
    _importing()
    try:
        record = imports_module.start(_host(), _host().current_owner(), request.get_json(silent=True) or {})
    except imports_module.Refused as refused:
        raise ApiError(refused.status, refused.message, refused.code)
    except ProviderRateLimited:
        raise ApiError(503, "Hugging Face is limiting requests. Try again in a few minutes.", "provider_rate_limited")
    except ProviderUnavailable:
        raise ApiError(503, "Hugging Face could not be reached. Try again in a few minutes.", "provider_unavailable")
    return jsonify(record), 202


@library_bp.route("/imports", methods=["GET"])
def list_imports():
    """The signed-in user's imports, newest first."""
    _importing()
    return jsonify({"imports": imports_module.for_owner(_host(), _host().current_owner())})


# Not `<import_id>`: hosts may treat `*_id` URL parameters as their own database ids.
@library_bp.route("/imports/<import_ref>", methods=["GET"])
def follow_import(import_ref):
    _importing()
    record = imports_module.get(_host(), _host().current_owner(), import_ref)
    if record is None:
        raise ApiError(404, "No such import.", "not_found")
    return jsonify(record)
