# KPI card: Parks and Green/Recreation Feature Density Score

## Purpose

Help buyers and buyer's agents compare mapped parks and related green/recreation features across two selected suburbs.

## Definition

Count distinct OpenStreetMap features tagged `leisure=park`, `leisure=garden`, `leisure=nature_reserve` or `leisure=playground` whose representative point falls within the suburb's latitude/longitude bounding box in `suburbs.csv`. Divide that count by the suburb's source `area_km2` to calculate features per square kilometre. Compare those densities within the selected pair, assigning the higher density 100 and scaling the other proportionally.

## Calculation

1. **Feature count:** unique OSM elements by element type and ID, filtered by the selected suburb's CSV `min_lat`, `min_lon`, `max_lat` and `max_lon` values. A mapped park and its separately mapped playground or garden can count as separate features.
2. **Suburb area:** the source CSV's `area_km2` value.
3. **Density:** `feature_count ÷ area_km2` features per km².
4. **Pair benchmark:** the higher density of the two selected suburbs.
5. **Score:** `min(100, 100 × suburb_density ÷ pair_benchmark_density)`. If both densities are zero, both scores are zero.

## Important boundary limitation

The attached CSV gives bounding rectangles, not actual suburb polygons. A rectangle may include mapped features beyond the suburb's true boundary. The supplied `area_km2` is the suburb area, not the rectangle area, so this count-over-area measure is indicative and can be biased for irregular or coastal suburbs. Exact suburb filtering requires polygon boundaries. The UI calls this a CSV bounding-box estimate.

## Wireframe placement

Place the KPI below the two-suburb selectors. Show each raw count, source area, density and pair-relative score together. Label the main result **CSV bounding-box estimate** and explain that counts may include features outside the true suburb boundary.

## Data and delivery notes

- The app queries only the two selected bounding boxes. It caches results for 24 hours, checks Supabase after the app cache, and syncs successful Overpass results to `public.amenity_counts` using `source=osm_overpass_bbox_green_recreation`.
- Run `supabase_osm_policy.sql` to permit reading and writing this source. Old `osm_overpass` records are circular, park-only legacy values; the app labels them if it must fall back to them.
- Public Overpass endpoints may be busy or unavailable, and very large CSV rectangles can take longer or fail. OSM coverage/tagging completeness also varies.
- Google Places is not queried in the current boundary-based KPI, so no search can reach its 60-result cap in this version. If the provider is introduced later, label a result of 60 as capped because additional places may exist.
- Display “© OpenStreetMap contributors.”
- The pair-relative benchmark changes when the comparison suburb changes. Use a fixed, dated benchmark for stable suburb rankings.
