"""Initial schema for the Instrument Scheduler.

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
    "Active",
    "Decommissioned",
    "UnderMaintenance",
    name="instrument_status",
    create_type=False,
)

audit_action_type_enum = postgresql.ENUM(
    "Create",
    "Update",
    "StatusChange",
    "SoftDelete",
    "ReservationCreated",
    "ReservationOverridden",
    name="audit_action_type",
    create_type=False,
)

audit_entity_type_enum = postgresql.ENUM(
    "Instrument",
    "Location",
    "Vendor",
    "Type",
    "ReservationPurpose",
    "Reservation",
    name="audit_entity_type",
    create_type=False,
)


def upgrade() -> None:
    bind = op.get_bind()

    instrument_status_enum.create(bind, checkfirst=True)
    audit_action_type_enum.create(bind, checkfirst=True)
    audit_entity_type_enum.create(bind, checkfirst=True)

    op.create_table(
        "locations",
        sa.Column("LocationID", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("Name", sa.String(length=120), nullable=False),
        sa.Column("NormalizedName", sa.String(length=120), nullable=False),
        sa.Column(
            "IsActive",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),
        sa.UniqueConstraint("NormalizedName", name="uq_locations_normalized_name"),
    )

    op.create_table(
        "vendors",
        sa.Column("VendorID", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("Name", sa.String(length=120), nullable=False),
        sa.Column("NormalizedName", sa.String(length=120), nullable=False),
        sa.Column(
            "IsActive",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),
        sa.UniqueConstraint("NormalizedName", name="uq_vendors_normalized_name"),
    )

    op.create_table(
        "types",
        sa.Column("TypeID", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("Name", sa.String(length=120), nullable=False),
        sa.Column("NormalizedName", sa.String(length=120), nullable=False),
        sa.Column(
            "IsActive",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),
        sa.UniqueConstraint("NormalizedName", name="uq_types_normalized_name"),
    )

    op.create_table(
        "reservation_purposes",
        sa.Column(
            "ReservationPurposeID",
            sa.Integer(),
            primary_key=True,
            autoincrement=True,
        ),
        sa.Column("Name", sa.String(length=120), nullable=False),
        sa.Column("NormalizedName", sa.String(length=120), nullable=False),
        sa.Column(
            "IsActive",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),
        sa.UniqueConstraint(
            "NormalizedName", name="uq_reservation_purposes_normalized_name"
        ),
    )

    op.create_table(
        "instruments",
        sa.Column("InstrumentID", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("Name", sa.String(length=120), nullable=False),
        sa.Column("Nickname", sa.String(length=120), nullable=False),
        sa.Column(
            "LocationID",
            sa.Integer(),
            sa.ForeignKey("locations.LocationID"),
            nullable=False,
        ),
        sa.Column(
            "VendorID",
            sa.Integer(),
            sa.ForeignKey("vendors.VendorID"),
            nullable=False,
        ),
        sa.Column(
            "TypeID",
            sa.Integer(),
            sa.ForeignKey("types.TypeID"),
            nullable=False,
        ),
        sa.Column("AssetID", sa.String(length=120), nullable=True),
        sa.Column("Color", sa.String(length=32), nullable=True),
        sa.Column("Status", instrument_status_enum, nullable=False),
        sa.Column(
            "IsActive",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),
        sa.Column(
            "IsFavorite",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )

    op.create_table(
        "reservations",
        sa.Column("ReservationID", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "InstrumentID",
            sa.Integer(),
            sa.ForeignKey("instruments.InstrumentID"),
            nullable=False,
        ),
        sa.Column("StartDateTime", sa.DateTime(timezone=True), nullable=False),
        sa.Column("EndDateTime", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "ReservationPurposeID",
            sa.Integer(),
            sa.ForeignKey("reservation_purposes.ReservationPurposeID"),
            nullable=False,
        ),
        sa.Column("RequestedBy", sa.String(length=120), nullable=False),
        sa.Column(
            "CanBeOverridden",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        sa.Column(
            "IsActive",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),
    )

    op.create_table(
        "audit_logs",
        sa.Column("AuditLogID", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("Actor", sa.String(length=120), nullable=False),
        sa.Column("Timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ActionType", audit_action_type_enum, nullable=False),
        sa.Column("EntityType", audit_entity_type_enum, nullable=False),
        sa.Column("EntityID", sa.Integer(), nullable=False),
        sa.Column("Description", sa.Text(), nullable=False),
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
    audit_entity_type_enum.drop(bind, checkfirst=True)
    audit_action_type_enum.drop(bind, checkfirst=True)
    instrument_status_enum.drop(bind, checkfirst=True)
