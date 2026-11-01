"""guest tables: guests, sessions, messages, feedback, events

Guest-keyed chat for the public demo. `feedback.session_id/message_id` and `events.session_id`
carry no foreign key on purpose: the 30-day purge deletes sessions (messages cascade) and those
rows must survive it.

The backend role gains just what the demo needs. It can delete only from `sessions` (the purge);
messages go by cascade, which runs with the table owner's rights. Isolation between guests is
done in SQL (`where guest_id = ...`): the backend connects as one role, so RLS policies here are
per role, not per guest.

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-07
"""
import os
import re

from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None

_NAME = re.compile(r"^[a-z_][a-z0-9_]{0,62}$")

# table -> commands the backend role may run
GRANTS = {
    "guests":   ("select", "insert", "update"),
    "sessions": ("select", "insert", "update", "delete"),
    "messages": ("select", "insert"),
    "feedback": ("select", "insert", "update"),
    "events":   ("select", "insert"),
}


def _role(var: str) -> str:
    name = os.environ.get(var, "").strip()
    if not _NAME.match(name):
        raise RuntimeError(f"{var} must be set to a lower-case role name (got {name!r})")
    return name


def upgrade() -> None:
    app = _role("DEMO_APP_ROLE")

    op.execute(
        """
        create table guests (
            id           uuid primary key,
            created_at   timestamptz not null default now(),
            last_seen_at timestamptz not null default now(),
            is_internal  boolean not null default false
        )
        """
    )
    op.execute(
        """
        create table sessions (
            id         uuid primary key default gen_random_uuid(),
            guest_id   uuid not null references guests (id) on delete cascade,
            title      text not null,
            created_at timestamptz not null default now(),
            updated_at timestamptz not null default now()
        )
        """
    )
    op.execute("create index sessions_guest_updated_idx on sessions (guest_id, updated_at desc)")
    op.execute("create index sessions_created_idx on sessions (created_at)")
    op.execute(
        "create trigger sessions_set_updated_at before update on sessions "
        "for each row execute function set_updated_at()"
    )
    op.execute(
        """
        create table messages (
            id         uuid primary key default gen_random_uuid(),
            session_id uuid not null references sessions (id) on delete cascade,
            guest_id   uuid not null references guests (id) on delete cascade,
            role       text not null check (role in ('user', 'assistant')),
            content    text not null,
            created_at timestamptz not null default now()
        )
        """
    )
    op.execute("create index messages_session_created_idx on messages (session_id, created_at desc)")
    op.execute("create index messages_guest_idx on messages (guest_id)")
    op.execute(
        """
        create table feedback (
            id         uuid primary key default gen_random_uuid(),
            guest_id   uuid not null references guests (id) on delete cascade,
            session_id uuid not null,
            message_id uuid not null unique,
            thumb      text not null check (thumb in ('up', 'down')),
            comment    text check (comment is null or char_length(comment) <= 2000),
            created_at timestamptz not null default now(),
            updated_at timestamptz not null default now()
        )
        """
    )
    op.execute("create index feedback_guest_idx on feedback (guest_id)")
    op.execute(
        """
        create table events (
            id         bigint generated always as identity primary key,
            guest_id   uuid not null references guests (id) on delete cascade,
            session_id uuid,
            type       text not null
                       check (type in ('session_started', 'recommendation_shown', 'route_drawn')),
            created_at timestamptz not null default now()
        )
        """
    )
    op.execute(
        "create unique index events_session_type_key on events (session_id, type) "
        "where session_id is not null"
    )
    op.execute("create index events_type_created_idx on events (type, created_at)")
    op.execute("create index events_guest_idx on events (guest_id)")

    tables = ", ".join(GRANTS)
    op.execute(f"revoke all on {tables} from public")
    for table, commands in GRANTS.items():
        op.execute(f"grant {', '.join(commands)} on {table} to {app}")
        op.execute(f"alter table {table} enable row level security")
        for command in commands:
            check = {
                "select": "using (true)",
                "delete": "using (true)",
                "insert": "with check (true)",
                "update": "using (true) with check (true)",
            }[command]
            op.execute(f"create policy {table}_app_{command} on {table} for {command} to {app} {check}")


def downgrade() -> None:
    # destructive on purpose: guest data cannot exist without these tables
    for table in ("events", "feedback", "messages", "sessions", "guests"):
        op.execute(f"drop table {table}")
