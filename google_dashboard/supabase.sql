begin;

create schema if not exists livability;
revoke all on schema livability from public;

-- Support the original CSV headers and the existing Demografy catalogue.
do $$
begin
    if exists (
        select 1 from information_schema.columns
        where table_schema = 'public' and table_name = 'suburbs'
          and column_name = 'suburb_name'
    ) then
        execute '
            create or replace view livability.suburb_catalog as
            select sal_code::text, suburb_name::text, state::text, postcode::text,
                   area_km2::float8, population::bigint,
                   min_lat::float8, min_lon::float8, max_lat::float8, max_lon::float8
            from public.suburbs where sal_code is not null';
    else
        execute '
            create or replace view livability.suburb_catalog as
            select sal_code::text, coalesce(sal_name, suburb)::text as suburb_name,
                   coalesce(state_abbr, state_name, '''')::text as state, postcode::text,
                   area_km2::float8, population::bigint,
                   min_lat::float8, min_lon::float8, max_lat::float8, max_lon::float8
            from public.suburbs where is_active and sal_code is not null';
    end if;
end
$$;

create table if not exists livability.place_snapshots (
    sal_code text not null,
    search_version integer not null,
    bounds jsonb not null,
    place_ids jsonb not null check (jsonb_typeof(place_ids) = 'object'),
    refreshed_at timestamptz not null default statement_timestamp(),
    primary key (sal_code, search_version)
);

create or replace view livability.amenity_metrics as
select snapshot.sal_code, snapshot.search_version, snapshot.bounds, snapshot.refreshed_at,
       transformed.counts
from livability.place_snapshots as snapshot
cross join lateral (
    select jsonb_object_agg(category, jsonb_array_length(ids)) as counts
    from jsonb_each(snapshot.place_ids) as places(category, ids)
) as transformed;

revoke all on livability.suburb_catalog, livability.place_snapshots,
              livability.amenity_metrics from public, anon, authenticated;

-- Use a dedicated login for the Streamlit server. Set its password separately.
do $$
begin
    if not exists (select 1 from pg_roles where rolname = 'livability_app') then
        create role livability_app login;
    end if;
end
$$;

grant usage on schema livability to livability_app;
grant select, insert, update on livability.place_snapshots to livability_app;
grant select on livability.suburb_catalog, livability.amenity_metrics to livability_app;

commit;
