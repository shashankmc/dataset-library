"""The HTTP API, under /api/library."""
from flask import Blueprint, current_app, jsonify, request

from . import policy as policy_module
from . import search as search_module
from .licenses import GROUPS, LICENSES
from .tasks import hugging_face_filter

library_bp = Blueprint("dataset_library", __name__)


class ApiError(Exception):
    def __init__(self, status, message, code):
        super().__init__(message)
        self.status = status
        self.body = {"error": message, "code": code}


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
            "sources": [
                {"value": s.ref, "label": s.ref, "provider": s.provider}
                for s in search_module.enabled_sources(host.db)
            ],
        }
    )
