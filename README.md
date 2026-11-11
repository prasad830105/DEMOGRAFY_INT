# Neighbourhood Livability Index

The Neighbourhood Livability Index is a Streamlit dashboard for comparing two Australian suburbs. Its **Weekend Escape Score** measures the concentration of parks and outdoor spaces and lets users personalise the comparison based on what matters to them.

## Key highlights

- **Suburb boundary comparison.** The current build uses Australian Bureau of Statistics (ABS) suburb polygons and Google Places Aggregate to count matching parks, national parks, playgrounds and gardens. Google can include a park whose polygon intersects the suburb boundary. [ABS suburb boundaries](https://www.abs.gov.au/statistics/standards/australian-statistical-geography-standard-asgs-edition-3/jul2021-jun2026/non-abs-structures/suburbs-and-localities) · [Google Places Aggregate](https://developers.google.com/maps/documentation/places-aggregate/request-parameters)
- **30-day cache.** Supabase serves fresh results. The app calls Google on a cache miss or after expiry, and a scheduled job deletes expired counts.
- **100-point benchmark.** The app divides matching outdoor places by the suburb area in km². The highest fresh positive density outside central business districts sets 100. Other density scores are scaled against that reference, capped at 100 and rounded down to the nearest five points. The benchmark updates as measurements arrive or expire.
- **Personalised scores.** Users weight the total-places score and the density score. Groq can suggest weights from typed preferences. The app highlights the higher score, explains what drove it and uses Excellent, Good, Fair and Poor ratings.

## Setup

The published `main` branch runs the rectangular Google Places Text Search dashboard and includes a standalone ABS polygon pilot. The current workspace build adds the default polygon comparison, its cache and the live benchmark described above.

1. Install the Python dependencies with `python -m pip install -r requirements.txt`.
2. Import [suburbs.csv](suburbs.csv) into `public.suburbs` in Supabase, or use an existing compatible suburb catalogue. Run [supabase.sql](supabase.sql) in the Supabase SQL Editor. If your checkout includes `boundary_cache.sql`, run it next to create the polygon cache, score views and expiry job.
3. Set a password for the `livability_app` database role. Copy [.streamlit/secrets.example.toml](.streamlit/secrets.example.toml) to `.streamlit/secrets.toml` and set `SUPABASE_DB_URL` to the Session pooler URI on port `5432`. Use `livability_app.<project-ref>` as the username and URL-encode the role password. Keep the secrets file out of Git. [Supabase connection guide](https://supabase.com/docs/guides/database/connecting-to-postgres)
4. For the polygon build, enable Places Aggregate API and set `GOOGLE_PLACES_AGGREGATE_API_KEY`. For rectangular search, enable Places API (New) and set `GOOGLE_PLACES_API_KEY`. Add `GROQ_API_KEY` to enable AI suggestions. On the published `main` branch, run `python measure.py` to populate the reference sample used by the rectangular dashboard.
5. Run `python -m streamlit run app.py`, open `http://localhost:8501` and compare two suburbs. For a local preview with sample data, set `LIVABILITY_DEMO = true` in the secrets file.
