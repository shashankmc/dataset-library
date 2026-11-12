import pytest

from tests.conftest import ALICE


def search(client, **params):
    resp = client.get("/api/library/search", query_string=params, headers=ALICE)
    assert resp.status_code == 200, resp.get_json()
    return resp.get_json()


def by_id(body):
    return {r["externalId"]: r for r in body["results"]}


def test_search_returns_hugging_face_datasets_as_cards(client):
    body = search(client, q="lex_glue")

    assert body["status"] == "ok"
    lex_glue = by_id(body)["coastalcph/lex_glue"]
    assert lex_glue["id"] == "huggingface:coastalcph/lex_glue"
    assert lex_glue["provider"] == "huggingface"
    assert lex_glue["title"] == "LexGLUE"
    assert lex_glue["url"] == "https://huggingface.co/datasets/coastalcph/lex_glue"
    # question-answering has no task type in legal-ml-core, so only classification shows.
    assert lex_glue["tasks"] == ["classification"]
    assert lex_glue["license"]["id"] == "cc-by-4.0"
    assert lex_glue["license"]["level"] == "allow"
    assert lex_glue["size"] == {"label": "100K–1M rows", "min": 100000, "max": 1000000}
    assert lex_glue["gated"] is False
    assert lex_glue["description"].startswith("Inspired by the recent widespread use of the GLUE")
    assert len(lex_glue["description"]) <= 300


def test_a_dataset_without_a_pretty_name_or_license_still_reads_well(client):
    lexglue = by_id(search(client, q="lexglue"))["lighteval/lexglue"]

    assert lexglue["title"] == "lexglue"
    assert lexglue["license"]["id"] == "unknown"
    assert lexglue["license"]["level"] == "warn"
    assert lexglue["tasks"] == []


def test_filters_by_task_and_license(client, hub):
    body = search(client, q="legal", task="classification", license="cc-by-4.0")

    assert sorted(by_id(body)) == ["AI-team-UoA/greek_legal_code", "nguha/legalbench"]
    assert hub.calls[-1]["params"]["filter"] == ["task_categories:text-classification", "license:cc-by-4.0"]
    assert all("classification" in r["tasks"] for r in body["results"])


def test_a_task_the_hub_has_no_tag_for_finds_nothing_without_asking(client, hub):
    body = search(client, q="legal", task="topic_modeling")

    assert body == {"status": "ok", "results": [], "count": 0}
    assert hub.calls == []


def test_an_unknown_task_or_license_is_refused(client):
    for params in ({"task": "poetry"}, {"license": "beerware"}):
        resp = client.get("/api/library/search", query_string=params, headers=ALICE)
        assert resp.status_code == 400
        assert resp.get_json()["code"] == "bad_filter"


def test_search_needs_sign_in(client, hub):
    assert client.get("/api/library/search", query_string={"q": "lex"}).status_code == 401
    assert hub.calls == []


def _set_policy(app, policy):
    from dataset_library.models import LibrarySettings

    with app.app_context():
        app.db.session.add(LibrarySettings(id=1, license_policy=policy))
        app.db.session.commit()


def test_a_hidden_license_never_shows_and_an_admins_level_does(app, client):
    _set_policy(app, {"mit": "hide", "cc-by-4.0": "warn"})

    found = by_id(search(client, q="legal"))

    assert "dataflare/egypt-legal-corpus" not in found  # MIT
    assert found["nguha/legalbench"]["license"]["level"] == "warn"


def test_searching_for_a_hidden_license_finds_nothing(app, client, hub):
    _set_policy(app, {"mit": "hide"})

    assert search(client, q="legal", license="mit")["results"] == []


def test_no_license_stated_can_be_searched_for(client, hub):
    found = by_id(search(client, q="caselaw", license="unknown"))

    assert sorted(found) == ["DanKamNdi/caselaw-v2-small", "DanKamNdi/sheria-caselaw", "TeraflopAI/Caselaw-Access-Project"]
    assert "filter" not in hub.calls[-1]["params"]


def test_the_same_search_within_ten_minutes_asks_the_hub_once(client, hub, cache):
    first = search(client, q="lex_glue")
    second = search(client, q="lex_glue")

    assert second == first
    assert len(hub.calls) == 1
    assert 600 in cache.ttls.values()


def test_a_policy_change_applies_to_cached_results_at_once(app, client, hub):
    search(client, q="legal")
    _set_policy(app, {"mit": "hide"})

    assert "dataflare/egypt-legal-corpus" not in by_id(search(client, q="legal"))
    assert len(hub.calls) == 1


def test_when_rate_limited_the_last_results_are_served_as_stale(client, hub, cache):
    fresh = search(client, q="lex_glue")
    cache.expire("library:search:")
    hub.fail = 429

    body = search(client, q="lex_glue")

    assert body["status"] == "stale"
    assert body["results"] == fresh["results"]


def test_when_rate_limited_with_nothing_cached_search_is_unavailable(client, hub):
    hub.fail = 429

    assert search(client, q="lex_glue") == {"status": "unavailable", "results": [], "count": 0}


@pytest.mark.parametrize("failure", [503, 500, "timeout", "malformed"])
def test_a_hub_failure_is_retried_once_then_reported_not_raised(client, hub, failure):
    hub.fail = failure

    body = search(client, q="lex_glue")

    assert body == {"status": "unavailable", "results": [], "count": 0}
    assert len(hub.calls) == 2


def _add_sources(app, *refs, enabled=True):
    from dataset_library.models import LibrarySource

    with app.app_context():
        for ref in refs:
            app.db.session.add(LibrarySource(provider="huggingface", kind="org", ref=ref, enabled=enabled))
        app.db.session.commit()


def test_enabled_sources_limit_search_to_their_organisations(app, client, hub):
    _add_sources(app, "coastalcph", "nguha")
    _add_sources(app, "free-law", enabled=False)

    found = by_id(search(client))

    assert {r.split("/")[0] for r in found} == {"coastalcph", "nguha"}
    assert sorted(c["params"]["author"] for c in hub.calls) == ["coastalcph", "nguha"]


def test_the_source_filter_picks_one_enabled_source(app, client, hub):
    _add_sources(app, "coastalcph", "nguha")

    found = by_id(search(client, source="nguha"))

    assert list(found) == ["nguha/legalbench"]
    resp = client.get("/api/library/search", query_string={"source": "free-law"}, headers=ALICE)
    assert resp.status_code == 400


def test_options_list_the_filters_and_the_license_table(app, client):
    _add_sources(app, "coastalcph")
    _set_policy(app, {"mit": "hide", "cc-by-4.0": "warn"})

    body = client.get("/api/library/options", headers=ALICE).get_json()

    assert [t["value"] for t in body["tasks"]] == ["classification", "ner", "summarization"]
    licenses = {lic["id"]: lic for lic in body["licenses"]}
    assert "mit" not in licenses
    assert licenses["cc-by-4.0"]["level"] == "warn"
    assert licenses["unknown"]["group"] == "Unknown"
    assert body["groups"] == ["Open", "Share-alike", "Non-commercial", "No-derivatives", "Unknown"]
    assert body["sources"] == [{"value": "coastalcph", "label": "coastalcph", "provider": "huggingface"}]
