"""events: travel mode, mode-change duration, repeatable mode_changed

`route_drawn` now records which travel mode the first route used. `mode_changed` is a new event
that can repeat within a session and carries how long the redraw took in the browser. The unique
index that keeps one row per session and type is narrowed so it does not apply to `mode_changed`.

Not additive for the running API: the 0004 insert names the old index predicate in its
`on conflict` clause, which no longer matches. Apply this together with the backend that carries
the matching statement (services/guest_store.py), not ahead of it.

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-08
"""
from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None

OLD_TYPES = "'session_started', 'recommendation_shown', 'route_drawn'"
NEW_TYPES = OLD_TYPES + ", 'mode_changed'"


def upgrade() -> None:
    op.execute(
        "alter table events add column mode text null "
        "constraint events_mode_check check (mode in ('car', 'bike', 'bus', 'walk'))"
    )
    op.execute(
        "alter table events add column duration_ms integer null "
        "constraint events_duration_ms_check check (duration_ms between 0 and 120000)"
    )
    op.execute("alter table events drop constraint events_type_check")
    op.execute(f"alter table events add constraint events_type_check check (type in ({NEW_TYPES}))")
    op.execute(
        "alter table events add constraint events_duration_only_on_mode_changed "
        "check (duration_ms is null or type = 'mode_changed')"
    )
    op.execute("drop index events_session_type_key")
    op.execute(
        "create unique index events_session_type_key on events (session_id, type) "
        "where session_id is not null and type <> 'mode_changed'"
    )


def downgrade() -> None:
    # destructive on purpose: mode_changed rows cannot exist under the 0004 constraints
    op.execute("delete from events where type = 'mode_changed'")
    op.execute("drop index events_session_type_key")
    op.execute(
        "create unique index events_session_type_key on events (session_id, type) "
        "where session_id is not null"
    )
    op.execute("alter table events drop constraint events_duration_only_on_mode_changed")
    op.execute("alter table events drop constraint events_type_check")
    op.execute(f"alter table events add constraint events_type_check check (type in ({OLD_TYPES}))")
    op.execute("alter table events drop column duration_ms")
    op.execute("alter table events drop column mode")
