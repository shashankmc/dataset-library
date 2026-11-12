"""The one license vocabulary.

Every provider resolves its license tags here, and the license policy and the
host UI read the same entries, so a license cannot mean one thing in search
and another at import. `level` is the default policy: `allow` imports without
a question; `warn` asks the student to confirm `ack`, after reading
`condition`. An admin can override the level per license (`hide` removes it
from search).
"""
from dataclasses import asdict, dataclass
from typing import Optional

GROUPS = ["Open", "Share-alike", "Non-commercial", "No-derivatives", "Unknown"]
LEVELS = ["allow", "warn", "hide"]

_NC_CONDITION = "{name} allows non-commercial use only. Coursework and research are fine; paid work for a client is not."
_NC_ACK = "I will use this dataset for study or research only, not commercially."
_ND_CONDITION = (
    "{name} forbids sharing modified versions. Sampling and annotating create one, "
    "so keep this dataset and its labels private."
)
_ND_ACK = "I will keep my copy and any labels I add private, and not share or publish them."
_SA_CONDITION = "If you share anything made from this data, you must share it under the same license."


@dataclass(frozen=True)
class License:
    id: str
    name: str
    group: str
    url: Optional[str]
    short: str
    nc: bool = False
    nd: bool = False
    sa: bool = False
    unknown: bool = False
    condition: Optional[str] = None
    ack: Optional[str] = None

    @property
    def level(self):
        """The default policy: confirm anything with a condition a student could break."""
        return "warn" if (self.nc or self.nd or self.unknown) else "allow"

    def to_dict(self):
        return {**asdict(self), "level": self.level}


def _cc(id_, name, path, short, nc=False, nd=False, sa=False):
    condition, ack = None, None
    if nd:
        condition, ack = _ND_CONDITION.format(name=name), _ND_ACK
    elif nc:
        condition, ack = _NC_CONDITION.format(name=name), _NC_ACK
        if sa:
            condition += " " + _SA_CONDITION
    elif sa:
        condition = _SA_CONDITION
    group = "No-derivatives" if nd else "Non-commercial" if nc else "Share-alike" if sa else "Open"
    return License(
        id=id_,
        name=name,
        group=group,
        url=f"https://creativecommons.org/licenses/{path}/",
        short=short,
        nc=nc,
        nd=nd,
        sa=sa,
        condition=condition,
        ack=ack,
    )


UNKNOWN = License(
    id="unknown",
    name="No license stated",
    group="Unknown",
    url=None,
    short="unknown",
    unknown=True,
    condition="This dataset does not say how it may be used. Without a license, you have no explicit permission to reuse it.",
    ack="I have checked that I may use this dataset, and I will not share or publish it.",
)

LICENSES = {
    lic.id: lic
    for lic in [
        License("cc0-1.0", "CC0 1.0", "Open", "https://creativecommons.org/publicdomain/zero/1.0/", "public domain"),
        _cc("cc-by-4.0", "CC BY 4.0", "by/4.0", "credit the authors"),
        _cc("cc-by-3.0", "CC BY 3.0", "by/3.0", "credit the authors"),
        _cc("cc-by-sa-4.0", "CC BY-SA 4.0", "by-sa/4.0", "share alike", sa=True),
        _cc("cc-by-sa-3.0", "CC BY-SA 3.0", "by-sa/3.0", "share alike", sa=True),
        _cc("cc-by-nc-4.0", "CC BY-NC 4.0", "by-nc/4.0", "non-commercial", nc=True),
        _cc("cc-by-nc-sa-4.0", "CC BY-NC-SA 4.0", "by-nc-sa/4.0", "non-commercial, share alike", nc=True, sa=True),
        _cc("cc-by-nc-nd-4.0", "CC BY-NC-ND 4.0", "by-nc-nd/4.0", "non-commercial, no derivatives", nc=True, nd=True),
        _cc("cc-by-nd-4.0", "CC BY-ND 4.0", "by-nd/4.0", "no derivatives", nd=True),
        License("mit", "MIT", "Open", "https://opensource.org/license/mit", "keep the notice"),
        License("apache-2.0", "Apache 2.0", "Open", "https://www.apache.org/licenses/LICENSE-2.0", "keep the notice"),
        License("odc-by", "ODC-By 1.0", "Open", "https://opendatacommons.org/licenses/by/1-0/", "credit the source"),
        License("pddl", "PDDL 1.0", "Open", "https://opendatacommons.org/licenses/pddl/1-0/", "public domain"),
        License(
            "odbl", "ODbL 1.0", "Share-alike", "https://opendatacommons.org/licenses/odbl/1-0/", "share alike",
            sa=True, condition=_SA_CONDITION,
        ),
        UNKNOWN,
    ]
}

# Other spellings of the same license: Hugging Face tags and fair-publishing ids.
ALIASES = {
    "cc0": "cc0-1.0",
    "odc-by-1.0": "odc-by",
    "odbl-1.0": "odbl",
    "pddl-1.0": "pddl",
    "apache2": "apache-2.0",
}


def resolve_license(tag):
    """The License for a provider's tag (`cc-by-4.0`, `license:cc-by-4.0`, `CC0`...).

    Missing, `other` and anything unrecognised resolve to UNKNOWN, so a
    license nobody checked is treated as one with a condition.
    """
    key = (tag or "").strip().lower().removeprefix("license:")
    key = ALIASES.get(key, key)
    return LICENSES.get(key, UNKNOWN)
