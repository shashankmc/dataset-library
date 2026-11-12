import pytest

from tests.conftest import ALICE


def labels(client, *ids):
    resp = client.get("/api/library/labels", query_string={"ids": ",".join(ids)}, headers=ALICE)
    assert resp.status_code == 200, resp.get_json()
    return resp.get_json()["labels"]


@pytest.mark.parametrize(
    "external_id, expected",
    [
        ("coastalcph/lex_glue", "yes"),  # class labels in its configs
        ("AI-team-UoA/greek_legal_code", "yes"),
        ("nguha/legalbench", "unclear"),  # a plain string `answer` column
        ("jfrenz/legalglue", "unclear"),  # the viewer cannot read it (501)
        ("free-law/Caselaw_Access_Project", "unclear"),  # gated (401)
    ],
)
def test_labels_come_from_the_datasets_own_column_types(client, external_id, expected):
    assert labels(client, f"huggingface:{external_id}") == {f"huggingface:{external_id}": expected}


def test_several_at_once_and_each_cached_for_an_hour(client, hub, cache):
    ids = ["huggingface:coastalcph/lex_glue", "huggingface:nguha/legalbench"]

    first = labels(client, *ids)
    calls = len(hub.calls)
    second = labels(client, *ids)

    assert first == second == {ids[0]: "yes", ids[1]: "unclear"}
    assert len(hub.calls) == calls
    assert 3600 in cache.ttls.values()


def test_a_bad_id_is_refused_without_asking_anyone(client, hub):
    resp = client.get("/api/library/labels", query_string={"ids": "huggingface:../etc/passwd"}, headers=ALICE)

    assert resp.status_code == 400
    assert hub.calls == []


def test_at_most_thirty_ids_per_request(client):
    ids = ",".join(f"huggingface:org/set{i}" for i in range(31))

    assert client.get("/api/library/labels", query_string={"ids": ids}, headers=ALICE).status_code == 400
