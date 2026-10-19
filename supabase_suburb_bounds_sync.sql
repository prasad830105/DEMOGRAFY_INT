-- Run after importing suburbs_import.csv into public.suburbs_import.
-- Existing rows are retained but deactivated; this CSV becomes the active list.
begin;

update public.suburbs set is_active = false;

insert into public.suburbs (
    suburb, sal_code, sal_name, state_code, state_name, state_abbr,
    centre_lat, centre_lon, is_active, legacy_name, postcode, area_km2,
    population, min_lat, min_lon, max_lat, max_lon
)
select
    suburb, sal_code, sal_name, state_code, state_name, state_abbr,
    centre_lat, centre_lon, true, nullif(legacy_name, ''), nullif(postcode, ''), area_km2,
    population, min_lat, min_lon, max_lat, max_lon
from public.suburbs_import
on conflict (suburb) do update set
    sal_code = excluded.sal_code,
    sal_name = excluded.sal_name,
    state_code = excluded.state_code,
    state_name = excluded.state_name,
    state_abbr = excluded.state_abbr,
    centre_lat = excluded.centre_lat,
    centre_lon = excluded.centre_lon,
    is_active = true,
    legacy_name = excluded.legacy_name,
    postcode = excluded.postcode,
    area_km2 = excluded.area_km2,
    population = excluded.population,
    min_lat = excluded.min_lat,
    min_lon = excluded.min_lon,
    max_lat = excluded.max_lat,
    max_lon = excluded.max_lon;

commit;
