from tests.conftest import ALICE


def preview(client, external_id, status=200, **params):
    resp = client.get(f"/api/library/datasets/huggingface/{external_id}", query_string=params, headers=ALICE)
    assert resp.status_code == status, resp.get_json()
    return resp.get_json()


def test_the_first_config_and_its_train_split_preview_by_default(client):
    body = preview(client, "AI-team-UoA/greek_legal_code")

    assert body["id"] == "huggingface:AI-team-UoA/greek_legal_code"
    assert body["title"] == "Greek Legal Code"
    assert body["preview"] == "ok"
    assert body["config"] == "volume" and body["split"] == "train"
    assert [c["name"] for c in body["configs"]] == ["volume", "chapter", "subject"]
    assert body["configs"][0]["splits"] == ["train", "test", "validation"]
    assert [c["name"] for c in body["columns"]] == ["text", "label"]
    assert body["columns"][0]["type"] == "text"
    assert body["columns"][1]["type"] == "class label, 47 classes"
    assert len(body["rows"]) == 8
    # Class labels arrive as numbers and are shown by name.
    assert all(isinstance(row[1], str) for row in body["rows"])
    assert body["labels"] == "yes"
    assert body["license"]["id"] == "cc-by-4.0"
    assert body["tasks"] == ["classification"]


def test_another_config_and_split_can_be_previewed(client):
    body = preview(client, "nguha/legalbench", config="hearsay", split="test")

    assert body["config"] == "hearsay" and body["split"] == "test"
    assert [c["name"] for c in body["columns"]] == ["index", "answer", "text", "slice"]
    assert body["columns"][0]["type"] == "number"
    assert body["rows"][0][1] == "No"
    assert body["labels"] == "unclear"


def test_the_description_is_its_first_paragraph_as_plain_text(client):
    body = preview(client, "coastalcph/lex_glue", config="ledgar")

    assert body["description"].startswith("Inspired by the recent widespread use of the GLUE")
    assert "\n" not in body["description"] and len(body["description"]) <= 300


def test_a_dataset_the_viewer_cannot_read_still_shows_its_facts(client):
    body = preview(client, "jfrenz/legalglue")

    assert body["preview"] == "unavailable"
    assert body["rows"] == [] and body["columns"] == []
    assert body["title"] == "LegalGLUE"
    assert body["tasks"] == ["classification", "ner"]


def test_a_gated_dataset_has_no_preview_and_says_it_is_gated(client):
    body = preview(client, "free-law/Caselaw_Access_Project")

    assert body["gated"] is True
    assert body["preview"] == "unavailable"


def test_an_unknown_config_is_refused(client):
    preview(client, "AI-team-UoA/greek_legal_code", status=400, config="nonsense")


def test_a_dataset_outside_the_library_is_not_found(app, client):
    from dataset_library.models import LibrarySettings, LibrarySource

    preview(client, "nobody/nothing", status=404)
    with app.app_context():
        app.db.session.add(LibrarySource(provider="huggingface", kind="org", ref="coastalcph"))
        app.db.session.add(LibrarySettings(id=1, license_policy={"mit": "hide"}))
        app.db.session.commit()
    preview(client, "nguha/legalbench", status=404)  # not an enabled source
    preview(client, "coastalcph/lex_glue", config="ledgar")


def test_a_hidden_license_is_not_found(app, client):
    from dataset_library.models import LibrarySettings

    with app.app_context():
        app.db.session.add(LibrarySettings(id=1, license_policy={"cc-by-4.0": "hide"}))
        app.db.session.commit()
    preview(client, "AI-team-UoA/greek_legal_code", status=404)


def test_a_path_like_id_never_leaves_the_server(client, hub):
    client.get("/api/library/datasets/huggingface/../../etc/passwd", headers=ALICE)
    resp = client.get("/api/library/datasets/huggingface/a/b/c", headers=ALICE)

    assert resp.status_code in (400, 404)
    assert hub.calls == []


def test_previews_are_cached_for_ten_minutes(client, hub):
    preview(client, "AI-team-UoA/greek_legal_code")
    calls = len(hub.calls)
    preview(client, "AI-team-UoA/greek_legal_code")

    assert len(hub.calls) == calls
