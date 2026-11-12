"""Library imports: one row per import, from queued to completed or failed (#113)."""
import sqlalchemy as sa
from alembic import op

revision = "dl_0002_imports"
down_revision = "dl_0001_settings_and_sources"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "library_imports",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("owner_id", sa.String(length=255), nullable=False),
        sa.Column("provider", sa.String(length=40), nullable=False),
        sa.Column("external_id", sa.String(length=200), nullable=False),
        sa.Column("config", sa.String(length=200), nullable=True),
        sa.Column("split", sa.String(length=200), nullable=True),
        sa.Column("revision", sa.String(length=80), nullable=True),
        sa.Column("url", sa.String(length=500), nullable=True),
        sa.Column("license", sa.String(length=80), nullable=False),
        sa.Column("license_ack_at", sa.DateTime(), nullable=True),
        sa.Column("text_column", sa.String(length=200), nullable=False),
        sa.Column("label_column", sa.String(length=200), nullable=True),
        sa.Column("task_type", sa.String(length=40), nullable=False),
        sa.Column("sample_size", sa.Integer(), nullable=False),
        sa.Column("max_rows", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("error_code", sa.String(length=40), nullable=True),
        sa.Column("error_message", sa.String(length=500), nullable=True),
        sa.Column("dataset_ref", sa.String(length=64), nullable=True),
        sa.Column("rows", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("imported_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_library_imports_owner_id", "library_imports", ["owner_id"])


def downgrade():
    op.drop_index("ix_library_imports_owner_id", table_name="library_imports")
    op.drop_table("library_imports")
