-- Run this in Supabase SQL Editor to allow the app to save OSM counts based on
-- CSV suburb bounding boxes. Seed rows below are legacy circular park-only
-- fallback values and will not overwrite current bounding-box counts.

drop policy if exists "Public can add demo amenity counts" on public.amenity_counts;
drop policy if exists "Public can add demo and OSM amenity counts" on public.amenity_counts;
create policy "Public can add demo and OSM amenity counts"
    on public.amenity_counts for insert to anon
    with check (source in ('illustrative_test_data', 'osm_overpass', 'osm_overpass_green_recreation', 'osm_overpass_bbox_green_recreation'));

drop policy if exists "Public can refresh demo amenity counts" on public.amenity_counts;
drop policy if exists "Public can refresh demo and OSM amenity counts" on public.amenity_counts;
create policy "Public can refresh demo and OSM amenity counts"
    on public.amenity_counts for update to anon
    using (source in ('illustrative_test_data', 'osm_overpass', 'osm_overpass_green_recreation', 'osm_overpass_bbox_green_recreation'))
    with check (source in ('illustrative_test_data', 'osm_overpass', 'osm_overpass_green_recreation', 'osm_overpass_bbox_green_recreation'));

insert into public.amenity_counts (suburb, category, place_count, source)
values
    ('Parramatta, NSW', 'Parks', 22, 'osm_overpass'),
    ('Chatswood, NSW', 'Parks', 16, 'osm_overpass'),
    ('Newtown, NSW', 'Parks', 46, 'osm_overpass')
on conflict (suburb, category) do update
set place_count = excluded.place_count,
    source = excluded.source
where public.amenity_counts.source <> 'osm_overpass_bbox_green_recreation';
