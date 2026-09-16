"""initial schema

Revision ID: 0001
Revises:
Create Date: 2024-01-01 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

instrument_status_enum = postgresql.ENUM(
    "AVAILABLE",
    "IN_USE",
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
    "TYPE",
    "RESERVATION_PURPOSE",
    "RESERVATION",
    name="audit_entity_type",
    create_type=False,
)


def upgrade() -> None:
    bind = op.get_bind()

    postgresql.ENUM(
        "AVAILABLE", "IN_USE", "MAINTENANCE", "DECOMMISSIONED", name="instrument_status"
    ).create(bind, checkfirst=True)
    postgresql.ENUM(
        "CREATE", "UPDATE", "DELETE", "ACTIVATE", "DEACTIVATE", "OVERRIDE", name="audit_action_type"
    ).create(bind, checkfirst=True)
    postgresql.ENUM(
        "INSTRUMENT", "LOCATION", "VENDOR", "TYPE", "RESERVATION_PURPOSE", "RESERVATION",
        name="audit_entity_type",
    ).create(bind, checkfirst=True)

    op.create_table(
        "locations",
        sa.Column("location_id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("normalized_name", sa.String(length=120), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("normalized_name", name="uq_locations_normalized_name"),
    )

    op.create_table(
        "vendors",
        sa.Column("vendor_id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("normalized_name", sa.String(length=120), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("normalized_name", name="uq_vendors_normalized_name"),
    )

    op.create_table(
        "types",
        sa.Column("type_id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("normalized_name", sa.String(length=120), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("normalized_name", name="uq_types_normalized_name"),
    )

    op.create_table(
        "reservation_purposes",
        sa.Column("reservation_purpose_id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("normalized_name", sa.String(length=120), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("normalized_name", name="uq_reservation_purposes_normalized_name"),
    )

    op.create_table(
        "instruments",
        sa.Column("instrument_id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("nickname", sa.String(length=120), nullable=False),
        sa.Column(
            "location_id",
            sa.Integer(),
            sa.ForeignKey("locations.location_id"),
            nullable=False,
        ),
        sa.Column(
            "vendor_id",
            sa.Integer(),
            sa.ForeignKey("vendors.vendor_id"),
            nullable=False,
        ),
        sa.Column(
            "type_id",
            sa.Integer(),
            sa.ForeignKey("types.type_id"),
            nullable=False,
        ),
        sa.Column("asset_id", sa.String(length=120), nullable=True),
        sa.Column("color", sa.String(length=30), nullable=True),
        sa.Column("status", instrument_status_enum, nullable=False, server_default="AVAILABLE"),
        sa.Column("is_favorite", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("start_datetime", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )

    op.create_table(
        "reservations",
        sa.Column("reservation_id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "instrument_id",
            sa.Integer(),
            sa.ForeignKey("instruments.instrument_id"),
            nullable=False,
        ),
        sa.Column("start_datetime", sa.DateTime(timezone=True), nullable=False),
        sa.Column("end_datetime", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "reservation_purpose_id",
            sa.Integer(),
            sa.ForeignKey("reservation_purposes.reservation_purpose_id"),
            nullable=False,
        ),
        sa.Column("requested_by", sa.String(length=120), nullable=True),
        sa.Column("can_be_overridden", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("end_datetime > start_datetime", name="ck_reservations_end_after_start"),
    )

    op.create_table(
        "audit_logs",
        sa.Column("audit_log_id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("actor", sa.String(length=120), nullable=False),
        sa.Column(
            "timestamp",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("action_type", audit_action_type_enum, nullable=False),
        sa.Column("entity_type", audit_entity_type_enum, nullable=False),
        sa.Column("entity_id", sa.Integer(), nullable=False),
        sa.Column("description", sa.String(length=1000), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("audit_logs")
    op.drop_table("reservations")
    op.drop_table("instruments")
    op.drop_table("reservation_purposes")
    op.drop_table("types")
    op.drop_table("vendors")
    op.drop_table("locations")

    bind = op.get_bind()
    postgresql.ENUM(name="audit_entity_type").drop(bind, checkfirst=True)
    postgresql.ENUM(name="audit_action_type").drop(bind, checkfirst=True)
    postgresql.ENUM(name="instrument_status").drop(bind, checkfirst=True)
