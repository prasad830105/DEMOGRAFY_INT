-- Run once to add CSV boundary fields and create a private import staging table.
alter table public.suburbs add column if not exists postcode text;
alter table public.suburbs add column if not exists area_km2 double precision;
alter table public.suburbs add column if not exists population bigint;
alter table public.suburbs add column if not exists min_lat double precision;
alter table public.suburbs add column if not exists min_lon double precision;
alter table public.suburbs add column if not exists max_lat double precision;
alter table public.suburbs add column if not exists max_lon double precision;

create table if not exists public.suburbs_import (
    suburb text not null,
    sal_code text not null primary key,
    sal_name text not null,
    state_code text not null,
    state_name text not null,
    state_abbr text not null,
    centre_lat double precision not null check (centre_lat between -90 and 90),
    centre_lon double precision not null check (centre_lon between -180 and 180),
    is_active boolean not null default true,
    legacy_name text,
    postcode text,
    area_km2 double precision not null check (area_km2 > 0),
    population bigint not null default 0,
    min_lat double precision not null check (min_lat between -90 and 90),
    min_lon double precision not null check (min_lon between -180 and 180),
    max_lat double precision not null check (max_lat between -90 and 90),
    max_lon double precision not null check (max_lon between -180 and 180),
    check (min_lat < max_lat),
    check (min_lon < max_lon)
);

alter table public.suburbs_import enable row level security;
