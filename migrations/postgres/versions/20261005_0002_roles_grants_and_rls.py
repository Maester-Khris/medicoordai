"""least-privilege roles, grants and row level security

Two application roles, names taken from the environment (never hardcoded, never with a password
here; set passwords out-of-band with ALTER ROLE):

  DEMO_APP_ROLE     backend: read-only
  DEMO_WORKER_ROLE  scraper worker: read facilities, insert new facilities, upsert wait times

Neither role can delete, truncate, create objects or update facilities. RLS is enabled on both
tables with explicit per-role policies, so any role without a policy sees no rows (default deny)
even if someone later grants it table privileges. The migration owner bypasses RLS by design
(table owner), which is what the one-time load and the manual enrichment scripts rely on.

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-05
"""
import os
import re

from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

_NAME = re.compile(r"^[a-z_][a-z0-9_]{0,62}$")


def _role(var: str) -> str:
    name = os.environ.get(var, "").strip()
    if not _NAME.match(name):
        raise RuntimeError(f"{var} must be set to a lower-case role name (got {name!r})")
    return name


def upgrade() -> None:
    app, worker = _role("DEMO_APP_ROLE"), _role("DEMO_WORKER_ROLE")
    if app == worker:
        raise RuntimeError("DEMO_APP_ROLE and DEMO_WORKER_ROLE must be different roles")

    for role in (app, worker):
        # LOGIN with no password: cannot authenticate until a password is set out-of-band
        op.execute(
            f"do $$ begin if not exists (select from pg_roles where rolname = '{role}') "
            f"then create role {role} login; end if; end $$"
        )

    op.execute("revoke all on facilities, wait_times from public")
    op.execute("revoke create on schema public from public")
    op.execute(f"grant usage on schema public to {app}, {worker}")

    op.execute(f"grant select on facilities, wait_times to {app}")
    op.execute(f"grant select, insert on facilities to {worker}")
    op.execute(f"grant select, insert, update on wait_times to {worker}")

    for table in ("facilities", "wait_times"):
        op.execute(f"alter table {table} enable row level security")
        op.execute(f"create policy {table}_app_select on {table} for select to {app} using (true)")
        op.execute(f"create policy {table}_worker_select on {table} for select to {worker} using (true)")
        op.execute(f"create policy {table}_worker_insert on {table} for insert to {worker} with check (true)")
    op.execute(f"create policy wait_times_worker_update on wait_times for update to {worker} using (true) with check (true)")


def downgrade() -> None:
    app, worker = _role("DEMO_APP_ROLE"), _role("DEMO_WORKER_ROLE")
    op.execute("drop policy wait_times_worker_update on wait_times")
    for table in ("facilities", "wait_times"):
        op.execute(f"drop policy {table}_worker_insert on {table}")
        op.execute(f"drop policy {table}_worker_select on {table}")
        op.execute(f"drop policy {table}_app_select on {table}")
        op.execute(f"alter table {table} disable row level security")
    op.execute(f"revoke all on facilities, wait_times from {app}, {worker}")
    op.execute(f"revoke usage on schema public from {app}, {worker}")
    # roles are left in place on purpose: dropping them would also drop whatever else they own
