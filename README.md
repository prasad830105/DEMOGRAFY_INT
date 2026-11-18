# Neighbourhood Livability Index

A Streamlit app that compares two Australian suburbs on one KPI: **Parks and Outdoor Spaces**. It uses Google Maps data to measure how many outdoor places each suburb offers and how concentrated they are.

The GitHub `main` branch runs the Text Search dashboard and includes a standalone ABS boundary pilot. The current local **Livability_v2** build adds a Places Aggregate toggle, a separate polygon cache and benchmark, and finer searches for busy suburbs. The setup below covers both versions.

## Run the app

1. Install the pinned Python dependencies.

   ```powershell
   python -m pip install -r requirements.txt
   ```

2. In Supabase, import [suburbs.csv](suburbs.csv) into `public.suburbs` or use an existing compatible suburb catalogue. Run [supabase.sql](supabase.sql) in the SQL Editor and set a password for the `livability_app` database role.
3. Copy [.streamlit/secrets.example.toml](.streamlit/secrets.example.toml) to `.streamlit/secrets.toml`. Set `SUPABASE_DB_URL` to the Supabase **Session pooler** URI on port 5432. Use `livability_app.<project-ref>` as the username and URL-encode the role password if needed. Set `GOOGLE_PLACES_API_KEY` to a key with **Places API (New)** enabled. Set `LIVABILITY_DEMO = false` for live data. Keep `secrets.toml` out of Git. [Supabase connection guide](https://supabase.com/docs/guides/database/connecting-to-postgres)
4. Start the app and open [localhost:8501](http://localhost:8501). Select two suburbs and click **Compare suburbs**.

   ```powershell
   python -m streamlit run app.py
   ```

For a preview without Google or Supabase credentials, set `LIVABILITY_DEMO = true` in the secrets file. On Windows, if `python` opens the Microsoft Store, use the full path to your installed Python executable.

## How the comparison works

- **Cache first.** The app checks Supabase for each suburb. Text Search reuses a matching snapshot for one calendar month. On a miss or after expiry, it fetches from Google and saves the result.
- **Search area.** Text Search finds places in the suburb’s bounding rectangle, which can include neighbouring suburbs. The local build searches for parks, dog parks and playgrounds by type. It splits areas that hit 60 results up to two levels, deduplicates place IDs and flags counts that may still be incomplete.
- **Density and the 100 mark.** Density is matching outdoor places divided by suburb area in km². Text Search scales each density against the highest density in a 12-suburb sample across Sydney, Melbourne and Brisbane, excluding CBDs. Scores cap at 100. In the local build, the score labels are Excellent (75–100), Good (50–74), Fair (25–49), and Limited (below 25). Run `python measure.py` on GitHub `main`, or `python refresh_benchmark.py` in the local build, to populate the sample.
- **Personal scores.** Users can weight total outdoor places and places per km². Add `GROQ_API_KEY` to enable weight suggestions from typed preferences. GitHub `main` also supports keyword suggestions. The local build uses a manual slider when Groq is unavailable and highlights the higher score with a short explanation.

## ABS boundary comparison in Livability_v2

Apply `boundary_cache.sql` after `supabase.sql`, enable **Places Aggregate API** in Google Cloud and set `GOOGLE_PLACES_AGGREGATE_API_KEY`. Turn on **Enable Places Aggregate API** before comparing suburbs. On GitHub `main`, the standalone [polygon pilot](google_boundary_pilot.py) runs with `python google_boundary_pilot.py` and uses `GOOGLE_PLACES_API_KEY` with Aggregate access enabled.

Places Aggregate counts parks, national parks, playgrounds and gardens using Australian Bureau of Statistics suburb polygons. A park with its own mapped boundary can count if any part overlaps the suburb. Google accepts a single exterior ring with up to 7,000 vertices, so some ABS shapes cannot be measured this way. [Google Places Aggregate request parameters](https://developers.google.com/maps/documentation/places-aggregate/request-parameters)

Supabase reuses fresh Aggregate measurements for up to 30 days and purges expired counts. The highest fresh parks density outside CBDs sets the Aggregate 100 mark, which updates as results arrive or expire. This mode rounds the scaled density score down to the nearest five points.

| Livability_v2 benchmark | Reference suburb | Verified on 18 November 2026 |
| --- | --- | --- |
| Places API (New) Text Search | Glebe, NSW | 34 places, 20.15 places/km² (12 suburbs sampled) |
| Places Aggregate | Zetland, NSW | 56 suburbs with fresh measurements out of 15,334 in the catalogue |

Suburb data and boundaries are from the Australian Bureau of Statistics, ASGS Edition 3 (2021), CC BY 4.0. Place data is from Google Maps. [ABS suburb boundaries](https://www.abs.gov.au/statistics/standards/australian-statistical-geography-standard-asgs-edition-3/jul2021-jun2026/non-abs-structures/suburbs-and-localities)
