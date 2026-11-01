# Postgres migrations (demo database)

All new Postgres migrations live here, as Alembic revisions in `versions/`. They target the
demo database (`medicoord-db-demo` on Railway) and are run unchanged against a local
throwaway Postgres 18 and the Railway one. The older `*.sql` files one level up are the
Supabase history and are not touched by this.

Stack: SQLAlchemy 2 + Alembic + psycopg 3 (in `backend/requirements.txt`). Hand-written
`op.*` migrations, no autogenerate. Keep them portable: no PostGIS in the first revisions
(the local image is plain `postgres:18`; PostGIS comes with the proximity-search work).

## Target database

`DATABASE_URL` selects the database; `env.py` prints the host/db/user it is about to touch.

```bash
source /home/niki/Documents/workenv/pydev/bin/activate

# local throwaway (port 5433, because 5432 belongs to another project's container)
export DATABASE_URL=postgresql+psycopg://postgres:postgres@localhost:5433/medicoord_demo

alembic -c migrations/postgres/alembic.ini current
alembic -c migrations/postgres/alembic.ini revision -m "create facilities"
alembic -c migrations/postgres/alembic.ini upgrade head
alembic -c migrations/postgres/alembic.ini downgrade -1
```

Remote (Railway): take the connection URL from `backend/.env.demo.local` (git-ignored) and
reach the database from the laptop through the Railway TCP proxy or a tunnel; then run the
same `upgrade head`. Check the printed `alembic target:` line before confirming anything.

## Local database

```bash
docker run -d --name medicoord-demo-pg -e POSTGRES_PASSWORD=postgres \
  -e POSTGRES_DB=medicoord_demo -p 127.0.0.1:5433:5432 postgres:18
docker rm -f medicoord-demo-pg   # throw it away and start again to re-test from zero
```

Local credentials are throwaway and only reachable on localhost.
