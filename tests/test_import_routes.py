"""Starting an import and following it (#113): POST /imports, GET /imports/<ref>."""
import pytest

from conftest import ALICE

BOB = {"X-User": "bob"}
LEXGLUE = {"dataset": "coastalcph/lex_glue", "config": "ledgar", "split": "train", "textColumn": "text", "labelColumn": "label", "size": 200}


class Queue:
    def __init__(self):
        self.refs = []
        self.down = False

    def __call__(self, import_ref):
        if self.down:
            raise ConnectionError("Redis is down")
        self.refs.append(import_ref)


@pytest.fixture
def queue():
    return Queue()


@pytest.fixture
def client(make_app, queue):
    return make_app(enqueue=queue, max_rows=lambda: 300).test_client()


def start(client, status=202, headers=ALICE, **body):
    response = client.post("/api/library/imports", json={**LEXGLUE, **body}, headers=headers)
    assert response.status_code == status, response.get_json()
    return response.get_json()


def test_an_import_is_queued_then_followed_by_its_owner_only(client, queue):
    started = start(client)

    assert started["status"] == "queued"
    assert started["name"] == "LexGLUE"
    assert started["license"] == "cc-by-4.0"
    assert started["revision"] == "c23fdff1a6bf74e0e1a71cb86f1e781d37da888c"
    assert started["url"] == "https://huggingface.co/datasets/coastalcph/lex_glue"
    assert queue.refs == [started["id"]]
    followed = client.get(f"/api/library/imports/{started['id']}", headers=ALICE)
    assert followed.status_code == 200
    assert followed.get_json() == started
    assert client.get(f"/api/library/imports/{started['id']}", headers=BOB).status_code == 404


def test_the_sample_is_cut_to_the_row_cap_read_when_queued(client):
    assert start(client, size=500)["size"] == 300
    assert start(client, size=50)["size"] == 50


def test_importing_the_same_dataset_again_is_named_with_its_number(client):
    start(client)
    assert start(client)["name"] == "LexGLUE (2)"
    assert start(client)["name"] == "LexGLUE (3)"
    assert start(client, headers=BOB)["name"] == "LexGLUE"


def test_a_license_set_to_warn_needs_the_students_confirmation(make_app, queue):
    app = make_app(enqueue=queue, max_rows=lambda: 300)
    from dataset_library.models import LibrarySettings

    with app.app_context():
        app.db.session.add(LibrarySettings(id=1, license_policy={"cc-by-4.0": "warn"}))
        app.db.session.commit()
    client = app.test_client()

    refused = start(client, status=409)
    assert refused["code"] == "needs_ack"
    assert queue.refs == []
    assert start(client, licenseAck=True)["status"] == "queued"


@pytest.mark.parametrize(
    "body, status, code",
    [
        ({"dataset": "not an id"}, 400, "bad_id"),
        ({"textColumn": "nope"}, 400, "bad_mapping"),
        ({"labelColumn": "nope"}, 400, "bad_mapping"),
        ({"size": 0}, 400, "bad_size"),
        ({"size": "lots"}, 400, "bad_size"),
        ({"taskType": "astrology"}, 400, "bad_task"),
        ({"dataset": "free-law/Caselaw_Access_Project", "config": None, "split": None}, 409, "gated"),
        ({"dataset": "jfrenz/legalglue", "config": None, "split": None}, 409, "not_importable"),
        ({"dataset": "nobody/nothing"}, 404, "not_found"),
    ],
)
def test_what_cannot_be_imported_is_refused_before_anything_is_queued(client, queue, body, status, code):
    assert start(client, status=status, **body)["code"] == code
    assert queue.refs == []


def test_with_the_queue_down_the_import_is_failed_and_the_student_told_to_try_again(client, queue):
    queue.down = True

    refused = start(client, status=503)

    assert refused["error"] == "Import could not start. Try again."
    [record] = client.get("/api/library/imports", headers=ALICE).get_json()["imports"]
    assert record["status"] == "failed"


def test_without_a_queue_the_host_offers_no_import(make_app):
    client = make_app().test_client()

    assert client.post("/api/library/imports", json=LEXGLUE, headers=ALICE).status_code == 404
    assert client.get("/api/library/options", headers=ALICE).get_json()["importable"] is False


def test_the_student_may_name_the_dataset(client):
    assert start(client, name="  Contract clauses  ")["name"] == "Contract clauses"
    assert start(client, name="")["name"] == "LexGLUE (2)"
    assert start(client, status=400, name="x" * 256)["code"] == "bad_name"
