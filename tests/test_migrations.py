"""The shipped revisions build the tables the models describe."""
import importlib.util
import pathlib

import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations

from dataset_library.models import LibraryBase

VERSIONS = pathlib.Path(__file__).parent.parent / "src/dataset_library/migrations/versions"


def _schema(engine):
    inspector = sa.inspect(engine)
    return {
        table: (
            {c["name"]: (str(c["type"]), c["nullable"]) for c in inspector.get_columns(table)},
            sorted(tuple(u["column_names"]) for u in inspector.get_unique_constraints(table)),
        )
        for table in inspector.get_table_names()
    }


def test_the_revisions_match_the_models():
    migrated = sa.create_engine("sqlite://")
    for path in sorted(VERSIONS.glob("dl_*.py")):
        spec = importlib.util.spec_from_file_location(path.stem, path)
        revision = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(revision)
        with migrated.begin() as connection:
            revision.op = Operations(MigrationContext.configure(connection))
            revision.upgrade()
    modelled = sa.create_engine("sqlite://")
    LibraryBase.metadata.create_all(modelled)

    assert _schema(migrated) == _schema(modelled)
