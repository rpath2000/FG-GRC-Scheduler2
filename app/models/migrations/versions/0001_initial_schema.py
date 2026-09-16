"""initial schema

Revision ID: 0001
Revises:
Create Date: 2026-07-23

"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


instrument_status_enum = postgresql.ENUM(
    "AVAILABLE",
    "MAINTENANCE",
    "DECOMMISSIONED",
    name="instrument_status",
    create_type=False,
)

audit_action_type_enum = postgresql.ENUM(
    "CREATE",
    "UPDATE",
    "DELETE",
    "ACTIVATE",
    "DEACTIVATE",
    "OVERRIDE",
    name="audit_action_type",
    create_type=False,
)

audit_entity_type_enum = postgresql.ENUM(
    "INSTRUMENT",
    "LOCATION",
    "VENDOR",
    "INSTRUMENT_TYPE",
    "RESERVATION_PURPOSE",
    "RESERVATION",
    name="audit_entity_type",
    create_type=False,
)


def upgrade() -> None:
    bind = op.get_bind()
    is_postgres = bind.dialect.name == "postgresql"

    if is_postgres:
        instrument_status_enum.create(bind, checkfirst=True)
        audit_action_type_enum.create(bind, checkfirst=True)
        audit_entity_type_enum.create(bind, checkfirst=True)

    op.create_table(
        "locations",
        sa.Column("location_id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("normalized_name", sa.String(length=200), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.UniqueConstraint("normalized_name", name="uq_locations_normalized_name"),
    )

    op.create_table(
        "vendors",
        sa.Column("vendor_id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("normalized_name", sa.String(length=200), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.UniqueConstraint("normalized_name", name="uq_vendors_normalized_name"),
    )

    op.create_table(
        "instrument_types",
        sa.Column("type_id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("normalized_name", sa.String(length=200), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.UniqueConstraint("normalized_name", name="uq_instrument_types_normalized_name"),
    )

    op.create_table(
        "reservation_purposes",
        sa.Column("reservation_purpose_id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("normalized_name", sa.String(length=200), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.UniqueConstraint("normalized_name", name="uq_reservation_purposes_normalized_name"),
    )

    op.create_table(
        "instruments",
        sa.Column("instrument_id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("normalized_name", sa.String(length=200), nullable=False),
        sa.Column("nickname", sa.String(length=200), nullable=False),
        sa.Column("location_id", sa.Integer(), sa.ForeignKey("locations.location_id"), nullable=False),
        sa.Column("vendor_id", sa.Integer(), sa.ForeignKey("vendors.vendor_id"), nullable=False),
        sa.Column("type_id", sa.Integer(), sa.ForeignKey("instrument_types.type_id"), nullable=False),
        sa.Column("asset_id", sa.String(length=100), nullable=True),
        sa.Column("color", sa.String(length=50), nullable=True),
        sa.Column(
            "status",
            instrument_status_enum if is_postgres else sa.String(length=20),
            nullable=False,
            server_default="AVAILABLE",
        ),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("is_favorite", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.UniqueConstraint("normalized_name", name="uq_instruments_normalized_name"),
    )
    op.create_index("ix_instruments_location_id", "instruments", ["location_id"])
    op.create_index("ix_instruments_vendor_id", "instruments", ["vendor_id"])
    op.create_index("ix_instruments_type_id", "instruments", ["type_id"])

    op.create_table(
        "reservations",
        sa.Column("reservation_id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("instrument_id", sa.Integer(), sa.ForeignKey("instruments.instrument_id"), nullable=False),
        sa.Column("start_datetime", sa.DateTime(timezone=True), nullable=False),
        sa.Column("end_datetime", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "reservation_purpose_id",
            sa.Integer(),
            sa.ForeignKey("reservation_purposes.reservation_purpose_id"),
            nullable=False,
        ),
        sa.Column("requested_by", sa.String(length=200), nullable=False),
        sa.Column("can_be_overridden", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.CheckConstraint("end_datetime > start_datetime", name="ck_reservations_end_after_start"),
    )
    op.create_index("ix_reservations_instrument_id", "reservations", ["instrument_id"])
    op.create_index("ix_reservations_purpose_id", "reservations", ["reservation_purpose_id"])
    op.create_index("ix_reservations_start_end", "reservations", ["start_datetime", "end_datetime"])

    op.create_table(
        "audit_logs",
        sa.Column("audit_log_id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("actor", sa.String(length=200), nullable=False),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "action_type",
            audit_action_type_enum if is_postgres else sa.String(length=20),
            nullable=False,
        ),
        sa.Column(
            "entity_type",
            audit_entity_type_enum if is_postgres else sa.String(length=30),
            nullable=False,
        ),
        sa.Column("entity_id", sa.Integer(), nullable=False),
        sa.Column("description", sa.String(length=2000), nullable=False),
    )
    op.create_index("ix_audit_logs_entity", "audit_logs", ["entity_type", "entity_id"])
    op.create_index("ix_audit_logs_timestamp", "audit_logs", ["timestamp"])


def downgrade() -> None:
    bind = op.get_bind()
    is_postgres = bind.dialect.name == "postgresql"

    op.drop_index("ix_audit_logs_timestamp", table_name="audit_logs")
    op.drop_index("ix_audit_logs_entity", table_name="audit_logs")
    op.drop_table("audit_logs")

    op.drop_index("ix_reservations_start_end", table_name="reservations")
    op.drop_index("ix_reservations_purpose_id", table_name="reservations")
    op.drop_index("ix_reservations_instrument_id", table_name="reservations")
    op.drop_table("reservations")

    op.drop_index("ix_instruments_type_id", table_name="instruments")
    op.drop_index("ix_instruments_vendor_id", table_name="instruments")
    op.drop_index("ix_instruments_location_id", table_name="instruments")
    op.drop_table("instruments")

    op.drop_table("reservation_purposes")
    op.drop_table("instrument_types")
    op.drop_table("vendors")
    op.drop_table("locations")

    if is_postgres:
        audit_entity_type_enum.drop(bind, checkfirst=True)
        audit_action_type_enum.drop(bind, checkfirst=True)
        instrument_status_enum.drop(bind, checkfirst=True)
