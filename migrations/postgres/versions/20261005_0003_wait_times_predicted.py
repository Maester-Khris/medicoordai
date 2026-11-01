"""wait_times: keep ERstat's predicted ranges, flagged

A predicted range ("45m–2h") has no single number, so it is stored as: predicted = true,
wait_minutes = NULL, raw_wait = the display text. A live wait keeps predicted = false and its
minutes. NULL (not 0, which would read as "no wait" and pass every wait filter) matches how the
backend already treats "no data". A check keeps the two shapes from mixing.

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-05
"""
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("alter table wait_times add column predicted boolean not null default false")
    op.execute("alter table wait_times alter column wait_minutes drop not null")
    op.execute(
        """
        alter table wait_times add constraint wait_times_live_or_predicted check (
            (predicted and wait_minutes is null and raw_wait is not null)
            or (not predicted and wait_minutes is not null)
        )
        """
    )


def downgrade() -> None:
    # destructive on purpose: predicted rows cannot exist without the column
    op.execute("delete from wait_times where predicted or wait_minutes is null")
    op.execute("alter table wait_times drop constraint wait_times_live_or_predicted")
    op.execute("alter table wait_times alter column wait_minutes set not null")
    op.execute("alter table wait_times drop column predicted")
