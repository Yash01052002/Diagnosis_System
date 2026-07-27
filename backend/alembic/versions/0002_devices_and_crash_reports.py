"""Devices, tags, device API keys and crash reports

Revision ID: 0002
Revises: 0001
Create Date: 2026-07-27
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "tags",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=50), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name="pk_tags"),
        sa.UniqueConstraint("name", name="uq_tags_name"),
    )
    op.create_index("ix_tags_name", "tags", ["name"], unique=True)

    op.create_table(
        "devices",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("device_id", sa.String(length=64), nullable=False),
        sa.Column("serial_number", sa.String(length=64), nullable=False),
        sa.Column("firmware_version", sa.String(length=50), nullable=False),
        sa.Column("hardware_model", sa.String(length=100), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="active"),
        sa.Column("location", sa.String(length=255), nullable=True),
        sa.Column("description", sa.String(length=500), nullable=True),
        sa.Column("owner_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("last_online_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["owner_id"], ["users.id"], name="fk_devices_owner_id_users", ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_devices"),
        sa.UniqueConstraint("device_id", name="uq_devices_device_id"),
        sa.UniqueConstraint("serial_number", name="uq_devices_serial_number"),
    )
    op.create_index("ix_devices_device_id", "devices", ["device_id"], unique=True)
    op.create_index("ix_devices_serial_number", "devices", ["serial_number"], unique=True)
    op.create_index("ix_devices_firmware_version", "devices", ["firmware_version"])
    op.create_index("ix_devices_hardware_model", "devices", ["hardware_model"])
    op.create_index("ix_devices_status", "devices", ["status"])
    op.create_index("ix_devices_owner_id", "devices", ["owner_id"])
    op.create_index("ix_devices_last_online_at", "devices", ["last_online_at"])

    op.create_table(
        "device_tags",
        sa.Column("device_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tag_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["device_id"],
            ["devices.id"],
            name="fk_device_tags_device_id_devices",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tag_id"], ["tags.id"], name="fk_device_tags_tag_id_tags", ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("device_id", "tag_id", name="pk_device_tags"),
    )

    op.create_table(
        "device_api_keys",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("device_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("prefix", sa.String(length=16), nullable=False),
        sa.Column("key_hash", sa.String(length=128), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("created_by_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["device_id"],
            ["devices.id"],
            name="fk_device_api_keys_device_id_devices",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_id"],
            ["users.id"],
            name="fk_device_api_keys_created_by_id_users",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_device_api_keys"),
        sa.UniqueConstraint("prefix", name="uq_device_api_keys_prefix"),
        sa.UniqueConstraint("key_hash", name="uq_device_api_keys_key_hash"),
    )
    op.create_index("ix_device_api_keys_device_id", "device_api_keys", ["device_id"])
    op.create_index("ix_device_api_keys_prefix", "device_api_keys", ["prefix"], unique=True)
    op.create_index("ix_device_api_keys_key_hash", "device_api_keys", ["key_hash"])

    op.create_table(
        "crash_reports",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("device_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("firmware_version", sa.String(length=50), nullable=False),
        sa.Column("build_version", sa.String(length=100), nullable=True),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("fault_type", sa.String(length=30), nullable=False, server_default="unknown"),
        sa.Column("exception_type", sa.String(length=100), nullable=True),
        sa.Column("task_name", sa.String(length=100), nullable=True),
        # 32-bit addresses do not fit a signed 32-bit column above 0x7FFFFFFF.
        sa.Column("program_counter", sa.BigInteger(), nullable=True),
        sa.Column("link_register", sa.BigInteger(), nullable=True),
        sa.Column("stack_pointer", sa.BigInteger(), nullable=True),
        sa.Column("register_dump", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("stack_dump", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("raw_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("parse_warnings", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("parser_version", sa.String(length=20), nullable=True),
        sa.Column("severity", sa.String(length=20), nullable=False, server_default="medium"),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="new"),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("ai_diagnosis", sa.Text(), nullable=True),
        sa.Column("suggested_fix", sa.Text(), nullable=True),
        sa.Column("confidence_score", sa.Float(), nullable=True),
        sa.Column("diagnosed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["device_id"],
            ["devices.id"],
            name="fk_crash_reports_device_id_devices",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_crash_reports"),
    )
    op.create_index("ix_crash_reports_device_id", "crash_reports", ["device_id"])
    op.create_index("ix_crash_reports_firmware_version", "crash_reports", ["firmware_version"])
    op.create_index("ix_crash_reports_build_version", "crash_reports", ["build_version"])
    op.create_index("ix_crash_reports_occurred_at", "crash_reports", ["occurred_at"])
    op.create_index("ix_crash_reports_fault_type", "crash_reports", ["fault_type"])
    op.create_index("ix_crash_reports_task_name", "crash_reports", ["task_name"])
    op.create_index("ix_crash_reports_severity", "crash_reports", ["severity"])
    op.create_index("ix_crash_reports_status", "crash_reports", ["status"])
    # Composite indexes for the two hottest queries: a device's recent crashes,
    # and fault-type breakdowns over a time window.
    op.create_index(
        "ix_crash_reports_device_id_occurred_at",
        "crash_reports",
        ["device_id", "occurred_at"],
    )
    op.create_index(
        "ix_crash_reports_fault_type_occurred_at",
        "crash_reports",
        ["fault_type", "occurred_at"],
    )


def downgrade() -> None:
    op.drop_table("crash_reports")
    op.drop_table("device_api_keys")
    op.drop_table("device_tags")
    op.drop_table("devices")
    op.drop_index("ix_tags_name", table_name="tags")
    op.drop_table("tags")
