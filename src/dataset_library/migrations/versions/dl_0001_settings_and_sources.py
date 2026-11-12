"""Library settings and sources.

Owned by the package. A host that runs Alembic adds this directory to its
``version_locations``; the branch label keeps it apart from the host's chain.
"""
import sqlalchemy as sa
from alembic import op

revision = "dl_0001_settings_and_sources"
down_revision = None
branch_labels = ("dataset_library",)
depends_on = None


def upgrade():
    op.create_table(
        "library_settings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("license_policy", sa.JSON(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_table(
        "library_sources",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("provider", sa.String(length=40), nullable=False),
        sa.Column("kind", sa.String(length=20), nullable=False),
        sa.Column("ref", sa.String(length=200), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("provider", "ref", name="uq_library_sources_ref"),
    )


def downgrade():
    op.drop_table("library_sources")
    op.drop_table("library_settings")
