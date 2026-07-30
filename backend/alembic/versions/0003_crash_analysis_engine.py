"""Crash analysis engine: firmware builds, symbols and crash groups

Revision ID: 0003
Revises: 0002
Create Date: 2026-07-27
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "crash_groups",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("signature", sa.String(length=64), nullable=False),
        sa.Column("signature_components", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("fault_type", sa.String(length=30), nullable=False),
        sa.Column("task_name", sa.String(length=100), nullable=True),
        sa.Column("top_function", sa.String(length=255), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="open"),
        sa.Column("severity", sa.String(length=20), nullable=False, server_default="medium"),
        sa.Column("occurrence_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("device_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "affected_firmware_versions",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("regressed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name="pk_crash_groups"),
        sa.UniqueConstraint("signature", name="uq_crash_groups_signature"),
    )
    op.create_index("ix_crash_groups_signature", "crash_groups", ["signature"], unique=True)
    op.create_index("ix_crash_groups_fault_type", "crash_groups", ["fault_type"])
    op.create_index("ix_crash_groups_top_function", "crash_groups", ["top_function"])
    op.create_index("ix_crash_groups_status", "crash_groups", ["status"])
    op.create_index("ix_crash_groups_first_seen_at", "crash_groups", ["first_seen_at"])
    op.create_index("ix_crash_groups_last_seen_at", "crash_groups", ["last_seen_at"])
    op.create_index("ix_crash_groups_status_last_seen", "crash_groups", ["status", "last_seen_at"])

    op.create_table(
        "firmware_builds",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("firmware_version", sa.String(length=50), nullable=False),
        sa.Column("build_version", sa.String(length=100), nullable=True),
        sa.Column("hardware_model", sa.String(length=100), nullable=True),
        sa.Column("artifact_type", sa.String(length=10), nullable=False, server_default="elf"),
        sa.Column("original_filename", sa.String(length=255), nullable=False),
        sa.Column("storage_path", sa.String(length=500), nullable=False),
        sa.Column("file_size", sa.BigInteger(), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("build_id", sa.String(length=64), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="pending"),
        sa.Column("arch", sa.String(length=30), nullable=True),
        sa.Column("has_debug_info", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("symbol_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("entry_point", sa.BigInteger(), nullable=True),
        sa.Column("sections", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("parse_warnings", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("indexed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("uploaded_by_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("notes", sa.String(length=500), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["uploaded_by_id"],
            ["users.id"],
            name="fk_firmware_builds_uploaded_by_id_users",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_firmware_builds"),
        # One artifact per (firmware, build, type); re-uploading replaces it.
        sa.UniqueConstraint(
            "firmware_version",
            "build_version",
            "artifact_type",
            name="uq_firmware_builds_version_build_type",
        ),
    )
    op.create_index("ix_firmware_builds_firmware_version", "firmware_builds", ["firmware_version"])
    op.create_index("ix_firmware_builds_build_version", "firmware_builds", ["build_version"])
    op.create_index("ix_firmware_builds_hardware_model", "firmware_builds", ["hardware_model"])
    op.create_index("ix_firmware_builds_sha256", "firmware_builds", ["sha256"])
    op.create_index("ix_firmware_builds_build_id", "firmware_builds", ["build_id"])
    op.create_index("ix_firmware_builds_status", "firmware_builds", ["status"])
    op.create_index(
        "ix_firmware_builds_firmware_build",
        "firmware_builds",
        ["firmware_version", "build_version"],
    )

    op.create_table(
        "build_symbols",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("build_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        # BigInteger: a signed 32-bit column cannot hold addresses > 0x7FFFFFFF.
        sa.Column("address", sa.BigInteger(), nullable=False),
        sa.Column("size", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("kind", sa.String(length=10), nullable=False, server_default="func"),
        sa.ForeignKeyConstraint(
            ["build_id"],
            ["firmware_builds.id"],
            name="fk_build_symbols_build_id_firmware_builds",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_build_symbols"),
    )
    # The hot query is "which symbol covers this address in this build".
    op.create_index("ix_build_symbols_build_address", "build_symbols", ["build_id", "address"])
    op.create_index("ix_build_symbols_build_name", "build_symbols", ["build_id", "name"])

    # -- crash_reports: symbolization and grouping --------------------------
    op.add_column(
        "crash_reports", sa.Column("crash_signature", sa.String(length=64), nullable=True)
    )
    op.add_column(
        "crash_reports", sa.Column("group_id", postgresql.UUID(as_uuid=True), nullable=True)
    )
    op.add_column(
        "crash_reports", sa.Column("build_id", postgresql.UUID(as_uuid=True), nullable=True)
    )
    op.add_column(
        "crash_reports",
        sa.Column("symbolication", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.add_column(
        "crash_reports", sa.Column("symbolicated_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column("crash_reports", sa.Column("top_function", sa.String(length=255), nullable=True))

    op.create_foreign_key(
        "fk_crash_reports_group_id_crash_groups",
        "crash_reports",
        "crash_groups",
        ["group_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_crash_reports_build_id_firmware_builds",
        "crash_reports",
        "firmware_builds",
        ["build_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index("ix_crash_reports_crash_signature", "crash_reports", ["crash_signature"])
    op.create_index("ix_crash_reports_group_id", "crash_reports", ["group_id"])
    op.create_index("ix_crash_reports_build_id", "crash_reports", ["build_id"])
    op.create_index("ix_crash_reports_top_function", "crash_reports", ["top_function"])


def downgrade() -> None:
    op.drop_index("ix_crash_reports_top_function", table_name="crash_reports")
    op.drop_index("ix_crash_reports_build_id", table_name="crash_reports")
    op.drop_index("ix_crash_reports_group_id", table_name="crash_reports")
    op.drop_index("ix_crash_reports_crash_signature", table_name="crash_reports")
    op.drop_constraint(
        "fk_crash_reports_build_id_firmware_builds", "crash_reports", type_="foreignkey"
    )
    op.drop_constraint(
        "fk_crash_reports_group_id_crash_groups", "crash_reports", type_="foreignkey"
    )
    op.drop_column("crash_reports", "top_function")
    op.drop_column("crash_reports", "symbolicated_at")
    op.drop_column("crash_reports", "symbolication")
    op.drop_column("crash_reports", "build_id")
    op.drop_column("crash_reports", "group_id")
    op.drop_column("crash_reports", "crash_signature")

    op.drop_table("build_symbols")
    op.drop_table("firmware_builds")
    op.drop_table("crash_groups")
