"""Instrument uniqueness is (name, nickname), not name alone.

The initial schema put a unique index on `lower(name)` for `instruments`, copied from the master-data
tables where it belongs -- the requirements make Location, Vendor, Type and Reservation Purpose names
unique. Instruments are deliberately not in that list, and the approved Instruments screen shows
`Biomek i7` three times (Alpha, Beta, Post Malone), `NovaSeq 6000` twice and `QIACube Classic` twice: a
model name is shared by every unit of that model and the NICKNAME distinguishes them.

So the database rejected rows the approved design requires. On the deployed app, creating the second
Biomek i7 answered "That location, vendor or type no longer exists" -- an IntegrityError is all the
handler sees, and a foreign key is the likelier cause of one.

`InstrumentService._check_duplicate` already enforces the correct rule (normalised name AND nickname)
and raises `DuplicateError`, which the page reports properly. This brings the schema into line with it.

Revision ID: 0002
Revises: 0001
"""
from alembic import op
import sqlalchemy as sa

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # `if_exists` because a database created from the current models rather than by replaying the
    # migrations will not have the old index, and a migration that only runs on one of those two is not
    # a migration.
    op.drop_index("uq_instruments_name_lower", table_name="instruments", if_exists=True)
    op.create_index(
        "uq_instruments_name_nickname_lower",
        "instruments",
        [sa.text("lower(name)"), sa.text("lower(nickname)")],
        unique=True,
        if_not_exists=True,
    )


def downgrade() -> None:
    op.drop_index("uq_instruments_name_nickname_lower", table_name="instruments", if_exists=True)
    # Deliberately NOT recreating the name-only index: it cannot be created while the data the approved
    # design requires is present, so a downgrade that tried would fail on any real dataset.
