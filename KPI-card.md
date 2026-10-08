# KPI card: Daily Needs Amenity Density Score

## Purpose

Give buyers and buyer's agents a comparable signal of how many everyday destinations are concentrated near a suburb centre. The current prototype uses a fixed 1 km straight-line radius as a practical, repeatable catchment.

> This is an amenity-density proxy, not a walking-time or 15-minute reachability measure. That future metric needs a pedestrian routing network and a defined residential starting point.

## Definition

For each category, count distinct Google Places within 1 km of the selected suburb centre, then divide by the circular catchment area. Convert each category density into a comparison score from 0 to 100, and average the category scores with equal weights.

| Category | Google Places API types (initial mapping) |
|---|---|
| Cafes | `cafe` |
| Parks | `park`, `city_park`, `botanical_garden` |
| Wellness | `gym`, `fitness_center`, `sports_complex`, `yoga_studio` |
| Childcare | `preschool`, `child_care_agency` |
| Transport | `bus_stop`, `train_station`, `subway_station`, `light_rail_station`, `tram_stop`, `transit_station` |

Place types are configurable, may overlap, and should be checked against the current Google Places API type list before implementation. Deduplicate results by Place ID across type searches.

## Calculation

1. **Count:** `category_count = distinct matching Place IDs inside 1 km`
2. **Catchment area:** `area_km2 = π × 1² = 3.1416 km²`
3. **Density:** `density_per_km2 = category_count / 3.1416`
4. **Comparison score (prototype):** for each category, `score = 100 × suburb_density / max(density for the two compared suburbs)`. If both densities are zero, both scores are zero.
5. **Overall KPI:** `mean(category scores)` across the five categories. Show category densities beside the overall score so the result stays explainable.

The comparison score is pair-relative: adding a different suburb can change the score. Before using it for saved rankings or comparisons across sessions, replace the pair maximum with a fixed reference distribution (for example, a metro/state cohort percentile) and document the cohort and refresh date. Equal category weighting is also a product decision for review.

## Wireframe placement

Place the KPI card directly below the suburb search and status message, before the category comparison. Keep the five category rows as the drill-down. Label the measure **Daily Needs Amenity Density Score** and the catchment as **within 1 km of suburb centre**. Do not label this calculation “15-minute walk” or “reachability.”

## Data and delivery notes

- The current dashboard values are illustrative fixtures, not live Google results.
- Store API keys in environment variables or Streamlit secrets; never commit secrets or `.env` files.
- A production implementation must confirm the suburb-centre geocoding method, API field mask, pagination/result completeness, cache duration, and Google Maps Platform storage/display terms.
- Validate category/type mappings with stakeholders; Google documents that one place can have multiple types. [Google Places API (New) place types](https://developers.google.com/maps/documentation/places/web-service/place-types)
