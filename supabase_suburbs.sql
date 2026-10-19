-- Run this migration before importing abs_sal_2026_suburbs.csv.
-- ABS ASGS Edition 4 (2026), Suburbs and Localities.
create table if not exists public.suburbs (
    suburb text primary key,
    centre_lat double precision not null check (centre_lat between -90 and 90),
    centre_lon double precision not null check (centre_lon between -180 and 180),
    is_active boolean not null default true
);

alter table public.suburbs add column if not exists sal_code text;
alter table public.suburbs add column if not exists sal_name text;
alter table public.suburbs add column if not exists state_code text;
alter table public.suburbs add column if not exists state_name text;
alter table public.suburbs add column if not exists state_abbr text;
alter table public.suburbs add column if not exists legacy_name text;

create unique index if not exists suburbs_sal_code_uidx
    on public.suburbs (sal_code) where sal_code is not null;
create index if not exists suburbs_name_search_idx
    on public.suburbs (lower(suburb));

alter table public.suburbs enable row level security;
do $$
begin
    if not exists (
        select 1 from pg_policies
        where schemaname = 'public'
          and tablename = 'suburbs'
          and policyname = 'Public can read active suburbs'
    ) then
        execute 'create policy "Public can read active suburbs" on public.suburbs for select to anon using (is_active = true)';
    end if;
end
$$;
grant select on public.suburbs to anon;
