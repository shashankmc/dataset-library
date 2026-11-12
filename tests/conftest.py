"""A minimal host: sign-in by an X-User header, an in-memory cache, and
Hugging Face faked at its HTTP boundary from recorded responses."""
import functools
import json
import pathlib

import pytest
import requests
from flask import Flask, abort, g, request
from flask_sqlalchemy import SQLAlchemy

from dataset_library import init_dataset_library
from dataset_library.models import LibraryBase

FIXTURES = pathlib.Path(__file__).parent / "fixtures" / "huggingface"
VIEWER = json.loads((pathlib.Path(__file__).parent / "fixtures" / "viewer" / "responses.json").read_text())
HUB_DATASETS = json.loads((pathlib.Path(__file__).parent / "fixtures" / "hub" / "datasets.json").read_text())
VIEWER_URL = "https://datasets-server.huggingface.co/"
DATASET_URL = "https://huggingface.co/api/datasets/"
TASK_TYPES = ["classification", "document_classification", "ner", "named_entity_recognition",
              "summarization", "topic_modeling", "clustering", "judgment_prediction"]


def login_required(view):
    @functools.wraps(view)
    def wrapped(*args, **kwargs):
        user = request.headers.get("X-User")
        if not user:
            abort(401)
        g.user = user
        return view(*args, **kwargs)

    return wrapped


class MemoryCache:
    def __init__(self):
        self.values = {}
        self.ttls = {}

    def get(self, key):
        return self.values.get(key)

    def set(self, key, value, ttl):
        self.values[key] = value
        self.ttls[key] = ttl

    def expire(self, prefix):
        """Forget fresh entries, as Redis would once their TTL ran out."""
        for key in [k for k in self.values if k.startswith(prefix)]:
            del self.values[key]


class FakeResponse:
    def __init__(self, status_code, body):
        self.status_code = status_code
        self._body = body
        self.text = body if isinstance(body, str) else json.dumps(body)

    def json(self):
        if isinstance(self._body, str):
            raise ValueError("not JSON")
        return self._body


class FakeHub:
    """Answers GET /api/datasets like the Hub: `search` matches the id, `author`
    the owner, every `filter` must be a tag. Records come from real responses."""

    def __init__(self):
        records = {}
        for path in sorted(FIXTURES.glob("*.json")):
            for record in json.loads(path.read_text()):
                records[record["id"]] = record
        self.records = list(records.values())
        self.calls = []
        self.fail = None  # an HTTP status, "malformed" or "timeout"

    def get(self, url, params=None, timeout=None, **kwargs):
        params = dict(params or {})
        self.calls.append({"url": url, "params": params, "timeout": timeout})
        if self.fail == "timeout":
            raise requests.Timeout("read timed out")
        if self.fail == "malformed":
            return FakeResponse(200, "<html>oops</html>")
        if self.fail:
            return FakeResponse(self.fail, {"error": "busy"})
        if url.startswith(VIEWER_URL):
            query = url.removeprefix(VIEWER_URL) + "?" + "&".join(f"{k}={params[k]}" for k in ("dataset", "config", "split") if k in params)
            recorded = VIEWER.get(query, {"status": 404, "body": {"error": "not recorded"}})
            return FakeResponse(recorded["status"], recorded["body"])
        if url.startswith(DATASET_URL):
            recorded = HUB_DATASETS.get(url.removeprefix(DATASET_URL), {"status": 404, "body": {"error": "Repository not found"}})
            return FakeResponse(recorded["status"], recorded["body"])
        assert url == "https://huggingface.co/api/datasets", url
        found = self.records
        if params.get("search"):
            found = [r for r in found if params["search"].lower() in r["id"].lower()]
        if params.get("author"):
            found = [r for r in found if r["id"].split("/")[0] == params["author"]]
        filters = params.get("filter") or []
        filters = [filters] if isinstance(filters, str) else filters
        found = [r for r in found if all(f in r["tags"] for f in filters)]
        return FakeResponse(200, found[: int(params.get("limit", 30))])


@pytest.fixture
def hub(monkeypatch):
    import dataset_library.providers.huggingface as hf

    fake = FakeHub()
    monkeypatch.setattr(hf.requests, "get", fake.get)
    return fake


@pytest.fixture
def cache():
    return MemoryCache()


@pytest.fixture
def audits():
    return []


@pytest.fixture
def make_app(cache, hub, audits):
    def make(**options):
        app = Flask(__name__)
        app.config.update({"TESTING": True, "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:", **options.pop("config", {})})
        db = SQLAlchemy()
        db.init_app(app)
        init_dataset_library(
            app,
            db=db,
            login_required=login_required,
            current_owner=lambda: g.user,
            task_types=TASK_TYPES,
            cache=cache,
            is_admin=lambda: request.headers.get("X-Admin") == "yes",
            audit=lambda event, **fields: audits.append({"event": event, **fields}),
            **options,
        )
        with app.app_context():
            LibraryBase.metadata.create_all(db.engine)
        app.db = db
        return app

    return make


@pytest.fixture
def app(make_app):
    return make_app()


@pytest.fixture
def client(app):
    return app.test_client()


ALICE = {"X-User": "alice"}
ADMIN = {"X-User": "ada", "X-Admin": "yes"}
