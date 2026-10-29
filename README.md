# Neighbourhood Livability Index

This Streamlit prototype compares **Parks & Outdoor Places** for two suburbs. The selectable suburb catalogue is generated from `suburbs.csv`. For this KPI, Overpass counts distinct OSM features tagged `leisure=park`, `leisure=garden`, `leisure=nature_reserve` or `leisure=playground` when their representative point falls inside that suburb's CSV latitude/longitude bounding box. Density is feature count divided by the CSV `area_km2`; the 0–100 score compares the two selected densities. Successful counts are cached for 24 hours and synced to Supabase. The display name is buyer-facing; the database category remains `Parks` for compatibility with existing data.

Google Places is not an active source in this boundary-based version, so it does not make Google searches or encounter the stated 60-result cap. If Google is added later, any search returning 60 results must be flagged as capped; the true count may be higher.

## Latest real comparison

The running app compared **Chatswood, NSW** with **Newtown, NSW** using saved OSM results read from Supabase:

| Suburb | Parks & Outdoor Places count | SAL area (km²) | Density (features/km²) | Pair-relative score |
| --- | ---: | ---: | ---: | ---: |
| Chatswood, NSW | 95 | 5.01 | 19.0 | 35/100 |
| Newtown, NSW | 86 | 1.59 | 54.2 | 100/100 |

Newtown receives the 100 mark because it has the higher **density**, even though its raw feature count is lower. The score is calculated against the higher density in this selected pair, so it changes when the comparison suburb changes. Counts come from OSM and use the suburb CSV bounding-box method; they are not exact SAL-polygon counts.

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

## Load Parks & Outdoor Places data for 60 suburbs

1. Start the app and turn on **Load KPI data for 60 suburbs**.
2. Use the bundled **Download 60-suburb starter list**, or upload a CSV with one column named `suburb`. Use full labels from the ABS catalogue, including state, such as `Chatswood, NSW`.
3. Select **Fetch KPI data and update Supabase**. Existing rows with source `osm_overpass_bbox_green_recreation` are reused first. Missing suburbs are queried from Overpass in batches of up to five bounding boxes, and successful counts are upserted into `public.amenity_counts`.
4. The results table shows the suburb, state, feature count and data source. Download the collected-counts CSV to keep a snapshot.

The importer accepts at most 60 unique suburbs per run to keep public Overpass usage reasonable. It requires the bundled `suburbs_import.csv` catalogue to contain the requested active suburbs and their bounds, and Supabase credentials/policies that permit reading and upserting the current OSM source. If an Overpass batch fails, successful saved results remain available and failed suburbs are listed so the import can be retried. OSM counts use representative points inside each SAL's rectangular extent, not exact SAL polygons.

For Streamlit Community Cloud, set `SUPABASE_URL` and `SUPABASE_KEY` under the app's Secrets settings. The current Supabase policies are for public illustrative/demo data; use authenticated, least-privilege policies before storing private or production data.

## Run the project checks

The mentor's original checker targets a different Google Places/PostgreSQL starter architecture. This repo uses OSM Overpass and Supabase REST, so `check.py` keeps the original A–E progression while checking the equivalent behavior in this app. Checks that touch APIs or Supabase use local fake responses; they do not make network requests or write to the database.

```powershell
python check.py A      # KPI, density, pair score, suburb catalogue
python check.py B      # Supabase REST filters/upsert shape and cache TTLs
python check.py C      # OSM query tags, batching and feature de-duplication
python check.py D      # suburb labels, saved-data reuse and five-suburb batches
python check.py E      # CSV bounding-box inclusion and limitation disclosure
python check.py ALL    # run every stage, stopping at the first failure
```

Stage E intentionally validates the app's current rectangular extent method, not exact SAL polygon containment. Exact-boundary checks require polygon geometry to be added to the app first.
