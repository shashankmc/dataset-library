"""What a course admin controls: the sources search looks in, and each
license's level (design review DR14). Saved whole, validated whole: one bad
field and nothing changes."""
from .licenses import LEVELS, LICENSES
from .models import LibrarySettings, LibrarySource
from .policy import level, overrides
from .providers import huggingface


class Invalid(Exception):
    def __init__(self, fields):
        super().__init__("Invalid settings")
        self.fields = fields


def current(db):
    policy = overrides(db)
    sources = db.session.query(LibrarySource).filter_by(provider="huggingface").order_by(LibrarySource.ref).all()
    return {
        "sources": [s.to_dict() for s in sources],
        "licenses": [
            {**lic.to_dict(), "default": lic.level, "level": level(lic, policy)} for lic in LICENSES.values()
        ],
    }


def check_source(ref):
    """None when `ref` is a Hugging Face organisation with public datasets, else why not.
    Raises ProviderError when the Hub cannot answer."""
    if not huggingface.ORGANISATION_PATTERN.match(ref or ""):
        return "That is not an organisation name. Use the part before the slash in a dataset id, e.g. lexlms."
    if not huggingface.organisation_has_datasets(ref):
        return f"No public datasets from “{ref}” on Hugging Face. Check the organisation’s name."
    return None


def save(db, body):
    """Replace the sources and the license policy. Returns what changed, for the audit."""
    sources = body.get("sources")
    policy = body.get("license_policy")
    fields = {}
    if not isinstance(sources, list):
        fields["sources"] = "A list of sources is required."
        sources = []
    if not isinstance(policy, dict):
        fields["license_policy"] = "License levels are required."
        policy = {}
    for license_id, chosen in policy.items():
        if license_id not in LICENSES:
            fields[f"license_policy.{license_id}"] = "Not a license the library knows."
        elif chosen not in LEVELS:
            fields[f"license_policy.{license_id}"] = "Choose Allow, Warn or Hide."

    existing = {s.ref: s for s in db.session.query(LibrarySource).filter_by(provider="huggingface")}
    seen = set()
    wanted = []
    for index, source in enumerate(sources):
        ref = (source or {}).get("ref", "").strip() if isinstance(source, dict) else ""
        if ref in seen:
            fields[f"sources.{index}"] = "This source is already listed."
            continue
        seen.add(ref)
        if ref not in existing:
            problem = check_source(ref)
            if problem:
                fields[f"sources.{index}"] = problem
                continue
        wanted.append((ref, bool(source.get("enabled", True))))
    if fields:
        raise Invalid(fields)

    before = {lic.id: level(lic, overrides(db)) for lic in LICENSES.values()}
    for ref, row in existing.items():
        if ref not in seen:
            db.session.delete(row)
    for ref, enabled in wanted:
        if ref in existing:
            existing[ref].enabled = enabled
        else:
            db.session.add(LibrarySource(provider="huggingface", kind="org", ref=ref, enabled=enabled))
    settings = db.session.get(LibrarySettings, 1)
    if settings is None:
        settings = LibrarySettings(id=1, license_policy={})
        db.session.add(settings)
    # Keep only levels that differ from the default, so a new default applies.
    settings.license_policy = {lid: lvl for lid, lvl in policy.items() if LICENSES[lid].level != lvl}
    db.session.commit()
    after = {lic.id: level(lic, settings.license_policy) for lic in LICENSES.values()}
    return {
        "sources_added": len([ref for ref, _ in wanted if ref not in existing]),
        "sources_removed": len([ref for ref in existing if ref not in seen]),
        "licenses_changed": sorted(lid for lid in LICENSES if before[lid] != after[lid]),
    }
