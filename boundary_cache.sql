begin;

create extension if not exists pg_cron;

create table if not exists livability.boundary_count_cache (
    sal_code text not null,
    search_version integer not null,
    place_count bigint check (place_count >= 0),
    -- A null count records a polygon that Google explicitly rejected.
    expires_at timestamptz not null,
    primary key (sal_code, search_version)
);

create index if not exists boundary_count_cache_expiry_idx
    on livability.boundary_count_cache (expires_at);

create or replace view livability.fresh_boundary_cache as
select sal_code, place_count is not null as measured
from livability.boundary_count_cache
where search_version = 1 and expires_at > statement_timestamp() + interval '1 minute';

create or replace function livability.store_boundary_count(target_sal_code text, measured_count bigint)
returns void
language sql
security definer
set search_path = pg_catalog, pg_temp
as $$
    insert into livability.boundary_count_cache as cache (sal_code, search_version, place_count, expires_at)
    select target_sal_code, 1, measured_count, statement_timestamp() + interval '720 hours'
    where exists (select 1 from livability.suburb_catalog where sal_code = target_sal_code)
    on conflict (sal_code, search_version) do update
    set place_count = excluded.place_count, expires_at = excluded.expires_at
    where cache.expires_at <= statement_timestamp() + interval '1 minute';
$$;

create or replace view livability.boundary_measurements as
select cache.sal_code, cache.place_count, cache.expires_at,
       cache.place_count / suburb.area_km2::numeric as density,
       concat_ws(', ', suburb.suburb_name, nullif(suburb.state, '')) as name,
       upper(trim(suburb.state)) as state,
       trim(regexp_replace(lower(suburb.suburb_name), '[-()[:space:]]+', ' ', 'g')) as normalized_name
from livability.boundary_count_cache as cache
join livability.suburb_catalog as suburb using (sal_code)
where cache.search_version = 1 and cache.place_count is not null
  and cache.expires_at > statement_timestamp() + interval '1 minute'
  and suburb.area_km2 > 0;

create or replace view livability.boundary_reference as
select name, density, max(place_count) over () as max_count
from livability.boundary_measurements
where density > 0 and not (
    'cbd' = any(string_to_array(normalized_name, ' ')) or (state, normalized_name) in (
        ('NSW', 'sydney'), ('NSW', 'sydney city'), ('NSW', 'parramatta'), ('NSW', 'newcastle'), ('NSW', 'wollongong'),
        ('VIC', 'melbourne'), ('VIC', 'melbourne city'), ('VIC', 'geelong'),
        ('QLD', 'brisbane'), ('QLD', 'brisbane city'), ('QLD', 'cairns'), ('QLD', 'townsville'),
        ('WA', 'perth'), ('WA', 'perth city'), ('SA', 'adelaide'), ('SA', 'adelaide city'),
        ('TAS', 'hobart'), ('TAS', 'launceston'), ('NT', 'darwin'), ('NT', 'darwin city'),
        ('ACT', 'canberra'), ('ACT', 'canberra city'), ('ACT', 'city'), ('ACT', 'civic')
    )
)
order by density desc, expires_at asc, sal_code asc
limit 1;

create or replace view livability.boundary_coverage as
select count(*)::integer as measured_suburbs,
       (select count(*)::integer from livability.suburb_catalog) as catalogue_suburbs,
       max(expires_at) - interval '720 hours' as published_at,
       min(expires_at) as expires_at
from livability.boundary_measurements;

create or replace view livability.current_boundary_benchmark as
select reference.name as benchmark_name, coverage.measured_suburbs, coverage.catalogue_suburbs,
       coverage.published_at, coverage.expires_at
from livability.boundary_reference as reference
cross join livability.boundary_coverage as coverage;

create or replace view livability.current_boundary_scores as
select measurement.sal_code,
       least(100, 5 * floor(20 * measurement.density / reference.density))::smallint as density_score,
       least(100, 5 * floor(20 * measurement.place_count::numeric / reference.max_count))::smallint as total_score,
       reference.name as benchmark_name, coverage.measured_suburbs, coverage.catalogue_suburbs, coverage.expires_at
from livability.boundary_measurements as measurement
cross join livability.boundary_reference as reference
cross join livability.boundary_coverage as coverage;

revoke all on livability.boundary_count_cache, livability.boundary_measurements, livability.boundary_reference,
    livability.boundary_coverage, livability.fresh_boundary_cache, livability.current_boundary_benchmark,
    livability.current_boundary_scores from public, anon, authenticated, livability_app;
revoke all on function livability.store_boundary_count(text, bigint) from public, anon, authenticated, livability_app;

grant select on livability.fresh_boundary_cache, livability.current_boundary_benchmark,
    livability.current_boundary_scores to livability_app;
grant execute on function livability.store_boundary_count(text, bigint) to livability_app;

-- Run before the 30-day deadline even for a fetch between scheduled minutes.
select cron.schedule('livability-purge-aggregate-counts', '* * * * *',
    $$delete from livability.boundary_count_cache where expires_at <= now() + interval '1 minute'$$);

commit;
