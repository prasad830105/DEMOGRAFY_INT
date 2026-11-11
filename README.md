# Neighbourhood Livability Index

The current Google Places dashboard compares **parks and outdoor places** for two Australian suburbs. Stage F converts typed preferences into editable 0–5 weights for total places and places per km². Keywords such as “toddler” and “no car” increase the concentration weight. A configured Groq key suggests weights and short reasons. Python computes the weighted personal score. The dashboard uses measured parks data for both measures.

## Run the Google Places dashboard

From the repository root:

```powershell
python -m pip install -r requirements.txt
python check.py F
python -m streamlit run app.py
```

Run [supabase.sql](supabase.sql) in the Supabase SQL Editor. If your catalogue is empty, import [suburbs.csv](suburbs.csv) into `public.suburbs` using the Table Editor. Set a password for the `livability_app` database role. Then copy [.streamlit/secrets.example.toml](.streamlit/secrets.example.toml) to `.streamlit/secrets.toml`. Set `SUPABASE_DB_URL` to the Session pooler URI for the restricted `livability_app` login and set `GOOGLE_PLACES_API_KEY` for Places API (New). Add `GROQ_API_KEY` for AI suggestions, or use the keyword assistant without a key. Enter general preferences only. The AI option sends the submitted text to Groq. Keep secrets out of Git.

## 100 mark and measured results

**South Brisbane, QLD sets 100 at 19.46 places per km²**. Google Places returned 39 unique IDs in its search rectangle and the ABS suburb area is 2.0041 km². The benchmark takes the highest density from 12 selected non-CBD suburbs across Sydney, Melbourne and Brisbane. Ten additional suburbs were measured and South Brisbane remained highest. Bondi Beach led the additional sample at 14.76/km².

| Suburb | Places | ABS area (km²) | Places per km² | Personal score at equal weights |
|---|---:|---:|---:|---:|
| Bondi, NSW | 12 | 0.8647 | 13.88 | 51/100 |
| Newtown, NSW | 6 | 1.5869 | 3.78 | 17/100 |

Equal weights compare total count with the sample maximum of 39 and density with 19.46/km². The pipeline uses IDs-only Google Text Search and counts unique IDs within rectangular bounds. Supabase reuses fresh results for one calendar month. Rectangles can include places beyond the actual suburb boundary. The separate three-suburb polygon pilot requires Google Places Aggregate API access.

Run `python measure.py` to refresh the reference sample or `python measure.py SAL10463` to check whether another eligible suburb beats the current mark. The latter flags a higher density for review.

Data credits are the [Australian Bureau of Statistics ASGS Suburbs and Localities](https://www.abs.gov.au/statistics/standards/australian-statistical-geography-standard-asgs-edition-3/jul2021-jun2026/non-abs-structures/suburbs-and-localities) for the catalogue, bounds and areas, and [Google Maps Places API](https://developers.google.com/maps/documentation/places/web-service/text-search) for the search results.

## Checks and boundary pilot

Run `python check.py ALL` to run the offline Livability v2 checks. Stage E checks the polygon request format. Run `python google_boundary_pilot.py` for the three-suburb live test after enabling Places Aggregate API on the Google project.
