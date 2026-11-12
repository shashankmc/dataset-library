import pytest

from dataset_library import resolve_license

# fair-publishing 0.1.0's DEFAULT_LICENSES: every id a Community dataset can carry.
FAIR_PUBLISHING_IDS = ["cc-by-4.0", "cc-by-sa-4.0", "cc-by-nc-4.0", "cc0-1.0", "mit", "apache-2.0"]


@pytest.mark.parametrize("tag", FAIR_PUBLISHING_IDS)
def test_every_fair_publishing_license_is_known(tag):
    assert not resolve_license(tag).unknown


@pytest.mark.parametrize(
    "tag, expected_id",
    [
        ("cc-by-4.0", "cc-by-4.0"),
        ("CC-BY-4.0", "cc-by-4.0"),
        ("license:cc-by-4.0", "cc-by-4.0"),
        ("cc0", "cc0-1.0"),
        ("cc0-1.0", "cc0-1.0"),
        ("apache-2.0", "apache-2.0"),
        ("odc-by", "odc-by"),
        ("cc-by-nc-sa-4.0", "cc-by-nc-sa-4.0"),
    ],
)
def test_hugging_face_tags_resolve_to_one_id(tag, expected_id):
    assert resolve_license(tag).id == expected_id


@pytest.mark.parametrize("tag", [None, "", "other", "unknown", "some-custom-license"])
def test_a_missing_or_unrecognised_license_is_unknown_and_warns(tag):
    license = resolve_license(tag)

    assert license.id == "unknown"
    assert license.unknown
    assert license.level == "warn"


def test_flags_and_default_levels():
    nd = resolve_license("cc-by-nd-4.0")
    assert nd.nd and not nd.nc and nd.level == "warn"
    assert nd.ack == "I will keep my copy and any labels I add private, and not share or publish them."

    nc_sa = resolve_license("cc-by-nc-sa-4.0")
    assert nc_sa.nc and nc_sa.sa and nc_sa.level == "warn"

    by = resolve_license("cc-by-4.0")
    assert not (by.nc or by.nd or by.sa or by.unknown) and by.level == "allow"
    assert by.group == "Open"
    assert by.url == "https://creativecommons.org/licenses/by/4.0/"
