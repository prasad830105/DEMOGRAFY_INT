# Neighbourhood Livability Index

This Streamlit prototype compares mapped parks and green/recreation features for two suburbs. The selectable suburb catalogue is generated from the attached `suburbs.csv`. For the main KPI, Overpass counts distinct OSM features tagged `leisure=park`, `leisure=garden`, `leisure=nature_reserve` or `leisure=playground` when their representative point falls inside that suburb's CSV latitude/longitude bounding box. Density is feature count divided by the CSV `area_km2`; the 0–100 score compares the two selected densities. Successful counts are cached for 24 hours and synced to Supabase.

Google Places is not an active source in this boundary-based version, so it does not make Google searches or encounter the stated 60-result cap. If Google is added later, any search returning 60 results must be flagged as capped; the true count may be higher.

## Run locally

```powershell
python -m pip install -r requirements.txt
python -m streamlit run app.py
```

## Update the suburb catalogue in Supabase

The bundled `suburbs_import.csv` has 15,334 suburbs and includes the source bounding boxes and areas. Regenerate it after replacing `suburbs.csv` with:

```powershell
python prepare_suburb_boundary_import.py
```

Then run these steps in Supabase:

1. Run [`supabase_schema.sql`](supabase_schema.sql) if `public.amenity_counts` has not been created.
2. Run [`supabase_suburbs.sql`](supabase_suburbs.sql) if `public.suburbs` has not been created.
3. Run [`supabase_suburb_bounds.sql`](supabase_suburb_bounds.sql) to add the CSV boundary fields and create a staging table.
4. In Table Editor, open `public.suburbs_import`, choose **Import data from CSV**, and upload `suburbs_import.csv`.
5. Run [`supabase_suburb_bounds_sync.sql`](supabase_suburb_bounds_sync.sql). It replaces the active suburb list with the CSV rows and updates each suburb's bounds and area.
6. Run [`supabase_osm_policy.sql`](supabase_osm_policy.sql) to allow the app to read and save OSM counts. For an existing project, the narrower [`supabase_osm_bbox_policy.sql`](supabase_osm_bbox_policy.sql) updates the current source allowlist, and [`supabase_amenity_counts_updated_at.sql`](supabase_amenity_counts_updated_at.sql) adds the timestamp column if it is missing.
7. Set `SUPABASE_URL` and `SUPABASE_KEY` in `.env` or Streamlit Secrets. Use the anon key, not a service-role key.

The CSV supplies bounding rectangles, not SAL polygon geometry. Rectangles can include places outside the actual suburb, while `area_km2` is the source suburb area. This makes the resulting density an approximation and can distort comparison, especially for irregular or coastal suburbs. Exact boundary filtering requires polygon geometries. The app labels this limitation alongside the score.

## Data and cache behavior

The app searches Supabase first and falls back to the bundled `suburbs_import.csv` if Supabase is unavailable. On Compare, it checks the in-process 24-hour cache, then Supabase rows with source `osm_overpass_bbox_green_recreation`, then queries Overpass for only the selected pair. Successful live counts are saved to `public.amenity_counts`. The app can display older circular park-only Supabase rows as a clearly labeled legacy fallback if Overpass is unavailable; refresh live OSM counts to replace them with current boundary-based results. Illustrative sample counts are no longer used.

Public Overpass endpoints can be unavailable or impose load limits, and very large bounding boxes may be slow or fail. The app tries several public endpoints. OSM coverage and tagging completeness vary. OSM attribution is shown in the app.

For Streamlit Community Cloud, set `SUPABASE_URL` and `SUPABASE_KEY` under the app's Secrets settings. The current Supabase policies are for public illustrative/demo data; use authenticated, least-privilege policies before storing private or production data.
