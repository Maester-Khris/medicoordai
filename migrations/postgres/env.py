"""Alembic environment for the demo Postgres database.

Hand-written migrations (op.*), no autogenerate: the schema lives in the versions, not in models.
The target comes from DATABASE_URL and is printed (without credentials) before anything runs,
so a migration against the wrong database is visible in the output.
"""

import os
import sys

from alembic import context
from sqlalchemy import create_engine, pool
from sqlalchemy.engine import make_url

config = context.config
target_metadata = None


def _database_url() -> str:
    raw = os.environ.get("DATABASE_URL", "").strip()
    if not raw:
        sys.exit("DATABASE_URL is not set (see migrations/postgres/README.md)")
    # accept the plain postgres:// and postgresql:// forms Railway hands out; we use psycopg 3
    for prefix in ("postgres://", "postgresql://"):
        if raw.startswith(prefix):
            raw = "postgresql+psycopg://" + raw[len(prefix):]
    return raw


def _announce(url: str) -> None:
    u = make_url(url)
    print(f"alembic target: {u.host}:{u.port}/{u.database} as {u.username}", file=sys.stderr)


def run_migrations_offline() -> None:
    context.configure(url=_database_url(), target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    url = _database_url()
    _announce(url)
    engine = create_engine(url, poolclass=pool.NullPool)
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
