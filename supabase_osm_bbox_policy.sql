-- Allow the app's current CSV-bounding-box OSM count source to be saved.
-- Extend the existing demo/legacy allowlist without replacing the policies.
alter policy "Public can add demo and OSM amenity counts"
    on public.amenity_counts
    with check (source in (
        'illustrative_test_data',
        'osm_overpass',
        'osm_overpass_green_recreation',
        'osm_overpass_bbox_green_recreation'
    ));

alter policy "Public can refresh demo and OSM amenity counts"
    on public.amenity_counts
    using (source in (
        'illustrative_test_data',
        'osm_overpass',
        'osm_overpass_green_recreation',
        'osm_overpass_bbox_green_recreation'
    ))
    with check (source in (
        'illustrative_test_data',
        'osm_overpass',
        'osm_overpass_green_recreation',
        'osm_overpass_bbox_green_recreation'
    ));
