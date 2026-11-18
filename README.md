# Neighbourhood Livability Index

A Streamlit dashboard for comparing the **Parks and Outdoor Spaces** KPI in two Australian suburbs. It uses Places API (New) Text Search by default, with an optional Google Places Aggregate comparison using ABS suburb boundaries. Both modes reuse fresh measurements from Supabase.

## Preview locally

From this folder, run the following in PowerShell. The app was verified with Python 3.14.6, and its direct dependencies are pinned in [requirements.txt](requirements.txt). If `python` resolves to the Microsoft Store alias, use the full path to your installed Python executable.

```powershell
python -m pip install -r requirements.txt
$env:LIVABILITY_DEMO = "true"
python -m streamlit run app.py
```

Click **Compare suburbs** to preview the dashboard with illustrative counts. Clear the demo setting for live data with `Remove-Item Env:LIVABILITY_DEMO`.

## Connect to Supabase

1. Run [supabase.sql](supabase.sql) in the Supabase SQL Editor. It creates a suburb catalogue if needed, plus the Text Search cache and a restricted `livability_app` login.
2. If the new `public.suburbs` table is empty, open it in Supabase Table Editor and import [suburbs.csv](suburbs.csv). The migration also supports the existing Demografy catalogue with `sal_name`, `state_abbr` and `is_active` columns. Set a password for `livability_app` in a private SQL session, for example with `\password livability_app` in psql.
3. From Supabase **Connect**, copy the **Session pooler** URI on port 5432. Replace the user with `livability_app.<project-ref>` and use the new role's password, URL-encoded where needed. Append `?sslmode=require` if the URI has no query string. [Supabase connection guide](https://supabase.com/docs/guides/database/connecting-to-postgres)
4. Copy [.streamlit/secrets.example.toml](.streamlit/secrets.example.toml) to `.streamlit/secrets.toml`. Fill in `SUPABASE_DB_URL` and `GOOGLE_PLACES_API_KEY`. Use a Google key with Places API (New) enabled. Leave `LIVABILITY_DEMO` false. The same settings can be passed as environment variables.
5. Run `python -m streamlit run app.py` and compare two suburbs. The app starts in Places API (New) Text Search mode. To compare using ABS polygons, follow the setup below and turn on **Enable Places Aggregate API** before submitting the comparison.

## Pipeline and caching

1. Streamlit loads the suburb catalogue, which it refreshes every 15 minutes. Users select known suburbs by name, state or postcode. SAL codes distinguish suburbs that share a name.
2. On submit, Python checks Supabase for both suburbs in parallel. A snapshot is reusable for one calendar month from the time it was fetched if its SAL code, bounds and search version still match. The first comparison after expiry fetches fresh results from Google Places and replaces the snapshot.
3. On a cache miss, a PostgreSQL transaction lock prevents a second worker from fetching the same suburb concurrently. The worker checks again after acquiring the lock. A request that reaches the lock timeout asks the user to retry.
4. The worker runs an IDs-only Google Text Search for each of `park`, `dog_park` and `playground`. A search that reaches 60 results is split into four quarters. A quarter that reaches the limit is split again. The worker deduplicates IDs across pages, boxes and place types. If a smallest box still hits the limit, the app warns that the count may be incomplete. [Google Text Search documentation](https://developers.google.com/maps/documentation/places/web-service/text-search)
5. The worker atomically replaces the snapshot after the search succeeds. A failed search rolls back its suburb transaction. The SQL view counts the stored IDs. Change `SEARCH_VERSION` when changing the search behaviour.

The app divides the number of unique places by the suburb area in km². Text Search uses the suburb's bounding rectangle, which can include places in nearby suburbs. The location map plots the midpoints of the two rectangles.

## Outdoor benchmark and AI

The highest Text Search density among 12 selected suburbs sets the 100-point benchmark. The sample uses four suburbs each from Sydney, Melbourne and Brisbane, with CBDs excluded. The app divides each suburb's density by the benchmark, multiplies by 100 and caps the score at 100. The ratings start at 75 for Excellent, 50 for Good and 25 for Fair. Scores below 25 are Limited.

Run `python refresh_benchmark.py` to fill or refresh the sample in Supabase. On an existing installation, reapply `supabase.sql` first to add the warning flag to the cache. The app displays the reference suburb once all 12 results are fresh. Pass SAL codes to measure additional suburbs and flag any density that beats the reference. The 12-suburb sample determines the Text Search benchmark.

Text Search results measured on 18 November 2026. **Glebe, NSW** set the benchmark at **20.15 places/km²**.

| Suburb | Matching places | Places per km² | Parks and Outdoor Spaces score | Rating |
| --- | ---: | ---: | ---: | --- |
| Glebe, NSW | 34 | 20.15 | 100.0/100 | Excellent |
| Newtown, NSW | 31 | 19.53 | 96.9/100 | Excellent |

Run `python google_boundary_pilot.py` to test Google Places Aggregate on ABS suburb polygons for Newtown, Carlton and South Brisbane. It makes at most three Google Aggregate requests and prints the counts. The pilot requires Places Aggregate API access on the configured Google project. Its polygon counts use a place type filter and are for evaluation alongside the rectangular Text Search benchmark. [Google Places Aggregate polygon examples](https://developers.google.com/maps/documentation/places-aggregate/example-requests)

Under **Personalise your parks comparison**, set the weight for total places. The remaining weight goes to places per km². Each measure is scored out of 100 against its highest value in the 12-suburb benchmark sample. The app combines those scores using the chosen weights. Set `GROQ_API_KEY` in Streamlit secrets to enable weight suggestions from typed preferences.

Run `python check.py ALL` for offline checks of the catalogue, scores, Supabase cache, Text Search pagination and subdivision, polygon measurements, and preference weighting. The checks use mock API responses and do not require credentials.

## Deploy and embed

Push the project to GitHub and create a public Streamlit Community Cloud app with `app.py` as the entry point. Add the production values in the Cloud app's secrets settings. For public release, link your site's terms of use and privacy policy from the published experience as required by Google Places. Replace the local iframe source in [embed.html](embed.html) with the deployed HTTPS URL, keeping `?embed=true`. Open the test HTML page and verify the comparison loads within the frame before using the same iframe on demografy.com.au. [Streamlit embedding guide](https://docs.streamlit.io/deploy/streamlit-community-cloud/share-your-app/embed-your-app)


## ABS boundary comparison

The optional comparison uses Google Places Aggregate with ABS SAL 2021 polygons and the types `park`, `national_park`, `playground` and `garden`. Google includes a park with its own polygon if it intersects the query area. Its custom-area endpoint accepts a single exterior ring with at most 7,000 vertices. The batch records coverage and skips shapes that fall outside these limits. [Google request parameters](https://developers.google.com/maps/documentation/places-aggregate/request-parameters)

1. After `supabase.sql`, apply or reapply [boundary_cache.sql](boundary_cache.sql) using the Supabase SQL Editor. It configures the private 30-day cache, schedules a purge with Supabase Cron, and grants the app login access to cache status, inserts through a database function, and derived scores.
2. Set `GOOGLE_PLACES_AGGREGATE_API_KEY` in Streamlit secrets or the environment. On **Compare suburbs**, the app checks Supabase before loading ABS polygons and calling Google. Results are saved before scoring. The highest fresh parks density outside CBDs sets 100, and Supabase calculates score bands against that reference as new results arrive and older results expire. [Google billing](https://developers.google.com/maps/billing-and-pricing/pricing) · [Google caching terms](https://cloud.google.com/maps-platform/terms/maps-service-terms#13-places-aggregate-api)
3. For bulk fetches, download the **Suburbs and Localities – 2021 – Shapefile** ZIP for GDA2020. The batch uses the published vertices as longitude and latitude for web mapping. The GDA2020 to WGS 84 null transformation has a stated accuracy of 3 metres. Set `SUPABASE_ADMIN_DB_URL` privately if `SUPABASE_DB_URL` uses the restricted app login. Run the preflight without Google requests. [ABS boundary downloads](https://www.abs.gov.au/statistics/standards/australian-statistical-geography-standard-asgs-edition-3/jul2021-jun2026/access-and-downloads/digital-boundary-files) · [ICSM geodetic reference](https://www.icsm.gov.au/sites/default/files/2022-08/AGRS_Compendium_20220816.pdf)

   ```powershell
   python boundary_batch.py SAL_2021_AUST_GDA2020_SHP.zip
   ```

4. Add `--fetch MAX_REQUESTS` to fetch up to that many suburbs with no fresh cache entry. Use `--fetch 0` to report the current benchmark and coverage without Google requests.

On 18 November 2026, **Zetland, NSW** set the Aggregate 100 mark, with fresh measurements for **56 of 15,334 suburbs**. Aggregate and Text Search have separate benchmarks because they use different search areas and place types.

Suburb data and boundaries are from the Australian Bureau of Statistics, ASGS Edition 3 (2021), CC BY 4.0. Place data is from Google Maps.
