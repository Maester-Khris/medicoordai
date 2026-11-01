"""create facilities and wait_times

One `facilities` table in the cleaned shape (the old raw/clean split is gone: nothing rebuilds
facilities_clean any more) and one-row-per-facility `wait_times` (current value; Redis holds the
live copy, history is not kept in the demo database).

Wait times exist only for hospitals: wait_times carries a constant category = 'hospital' and a
composite foreign key (facility_id, category) -> facilities(id, category), so the database itself
rejects a wait time for a clinic or care home (the matching bug found on 2026-10-05).

Revision ID: 0001
Revises:
Create Date: 2026-10-05
"""
from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        create table facilities (
            id                   uuid primary key default gen_random_uuid(),
            name                 text not null,
            category             text not null
                                 check (category in ('hospital', 'ambulatory', 'residential')),
            source_facility_type text not null,
            accepted_severity    text[] not null
                                 check (cardinality(accepted_severity) > 0
                                        and accepted_severity <@ array['emergent', 'urgent', 'moderate', 'routine']),
            address              text not null,
            lat                  double precision not null check (lat between -90 and 90),
            lng                  double precision not null check (lng between -180 and 180),
            phone                text,
            business_status      text,
            is_operational       boolean generated always as
                                 (coalesce(upper(business_status) = 'OPERATIONAL', false)) stored,
            weekday_hours        text,
            place_id             text,
            last_enriched_at     timestamptz,
            source               text not null default 'odhf'
                                 check (source in ('odhf', 'manual', 'other')),
            created_at           timestamptz not null default now(),
            updated_at           timestamptz not null default now(),
            constraint facilities_name_lat_lng_key unique (name, lat, lng),
            constraint facilities_id_category_key unique (id, category)
        )
        """
    )
    # provider-neutral id (Google Places before, Geoapify now); partial so unenriched rows can be NULL
    op.execute("create unique index facilities_place_id_key on facilities (place_id) where place_id is not null")

    op.execute(
        """
        create function set_updated_at() returns trigger language plpgsql as $$
        begin
            new.updated_at = now();
            return new;
        end;
        $$
        """
    )
    op.execute(
        "create trigger facilities_set_updated_at before update on facilities "
        "for each row execute function set_updated_at()"
    )

    op.execute(
        """
        create table wait_times (
            facility_id  uuid primary key,
            category     text not null default 'hospital' check (category = 'hospital'),
            wait_minutes integer not null check (wait_minutes >= 0),
            raw_wait     text,
            source       text,
            scraped_at   timestamptz not null,
            recorded_at  timestamptz not null default now(),
            foreign key (facility_id, category) references facilities (id, category) on delete cascade
        )
        """
    )


def downgrade() -> None:
    op.execute("drop table wait_times")
    op.execute("drop table facilities")
    op.execute("drop function set_updated_at()")
