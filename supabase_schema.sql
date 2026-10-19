-- Public illustrative demo data only. Tighten these policies before storing private data.
create table if not exists public.amenity_counts (
    suburb text not null,
    category text not null check (category in ('Cafes', 'Parks', 'Wellness', 'Childcare', 'Transport')),
    place_count integer not null check (place_count >= 0),
    source text not null default 'illustrative_test_data',
    updated_at timestamptz not null default now(),
    primary key (suburb, category)
);

alter table public.amenity_counts enable row level security;

drop policy if exists "Public can read demo amenity counts" on public.amenity_counts;
create policy "Public can read demo amenity counts"
    on public.amenity_counts for select to anon using (true);

drop policy if exists "Public can add demo amenity counts" on public.amenity_counts;
create policy "Public can add demo amenity counts"
    on public.amenity_counts for insert to anon with check (source = 'illustrative_test_data');

drop policy if exists "Public can refresh demo amenity counts" on public.amenity_counts;
create policy "Public can refresh demo amenity counts"
    on public.amenity_counts for update to anon
    using (source = 'illustrative_test_data')
    with check (source = 'illustrative_test_data');

grant select, insert, update on public.amenity_counts to anon;
