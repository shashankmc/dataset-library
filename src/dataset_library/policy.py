"""The license policy: each license's level, as an admin set it or by default."""
from .models import LibrarySettings


def overrides(db):
    settings = db.session.get(LibrarySettings, 1)
    return dict(settings.license_policy or {}) if settings else {}


def level(license, policy):
    return policy.get(license.id, license.level)
