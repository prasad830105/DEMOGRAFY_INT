"""Streamlit suburb parks-density comparison with Supabase and OSM data."""

from __future__ import annotations

import os
import time
import csv
from datetime import datetime, timezone
from pathlib import Path

import altair as alt
import pandas as pd
import requests
import streamlit as st

# Create a session with retry logic
from requests.adapters import HTTPAdapter
from urllib3.util import Retry

session = requests.Session()
retry_strategy = Retry(
    total=3,
    backoff_factor=1,
    status_forcelist=[500, 502, 503, 504],
    allowed_methods=["POST"],
)
session.mount("https://", HTTPAdapter(max_retries=retry_strategy))


def load_local_env() -> None:
    """Load simple KEY=VALUE entries from the ignored local .env file."""
    env_path = Path(__file__).with_name(".env")
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, value = line.split("=", 1)
        value = value.strip().strip("\"'")
        if name.strip() and value:
            os.environ.setdefault(name.strip(), value)


load_local_env()
st.set_page_config(page_title="Demografy | Neighbourhood comparison", page_icon="⌂", layout="wide")

CATEGORY = "Parks"
OSM_SOURCE = "osm_overpass_bbox_green_recreation"
OSM_LEISURE_TAGS = ("park", "garden", "nature_reserve", "playground")
OVERPASS_ENDPOINTS = (
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kaywa.de/api/interpreter",
    "https://overpass-api.eu/api/interpreter",
    "https://overpass-api.openstreetmap.de/api/interpreter",
    "https://overpass.private.coffee/api/interpreter",
    "https://maps.mail.ru/osm/tools/overpass/api/interpreter",
)


def setting(name: str) -> str:
    """Read settings from Streamlit secrets first, then the process environment."""
    try:
        value = st.secrets.get(name, "")
    except (FileNotFoundError, RuntimeError):
        value = ""
    return str(value or os.getenv(name, "")).strip()


def supabase_config() -> tuple[str, str]:
    return setting("SUPABASE_URL").rstrip("/"), setting("SUPABASE_KEY")


@st.cache_data(ttl=60 * 60, show_spinner=False)
def load_local_suburbs() -> list[dict]:
    """Load the prepared full suburb catalogue when Supabase is unavailable."""
    path = Path(__file__).with_name("suburbs_import.csv")
    if not path.exists():
        return []
    with path.open(encoding="utf-8-sig", newline="") as file:
        return list(csv.DictReader(file))


def local_suburb_matches(cleaned: str) -> list[dict]:
    query = cleaned.casefold()
    matches = [
        row for row in load_local_suburbs()
        if query in row["suburb"].casefold() or query in row["sal_name"].casefold()
    ]
    return sorted(matches, key=lambda row: (len(row["suburb"]), row["suburb"].casefold()))[:25]


def supabase_request(method: str, path: str, *, params=None, json=None, prefer=None):
    base_url, key = supabase_config()
    if not base_url or not key:
        raise RuntimeError("Supabase is not configured. Add SUPABASE_URL and SUPABASE_KEY to .env or Streamlit secrets.")
    headers = {"apikey": key, "Authorization": f"Bearer {key}", "Content-Type": "application/json"}
    if prefer:
        headers["Prefer"] = prefer
    response = requests.request(
        method,
        f"{base_url}/rest/v1/{path}",
        headers=headers,
        params=params,
        json=json,
        timeout=20,
    )
    response.raise_for_status()
    return response.json() if response.content else []


@st.cache_data(ttl=10 * 60, show_spinner=False)
def search_suburbs(query: str) -> tuple[list[dict], str | None]:
    """Search a small page of the ABS suburb catalogue, never load the full list."""
    cleaned = "".join(char for char in query if char.isalnum() or char in " ',-").strip()
    if len(cleaned) < 2:
        return [], None
    base_url, key = supabase_config()
    if not base_url or not key:
        matches = local_suburb_matches(cleaned)
        return matches, None
    try:
        rows = supabase_request(
            "GET",
            "suburbs",
            params={
                "select": "suburb,sal_code,sal_name,state_abbr,legacy_name,area_km2,min_lat,min_lon,max_lat,max_lon",
                "is_active": "eq.true",
                "suburb": f"ilike.*{cleaned}*",
                "order": "suburb.asc",
                "limit": "25",
            },
        )
        return sorted(rows, key=lambda row: (len(row["suburb"]), row["suburb"].casefold())), None
    except (requests.RequestException, ValueError, KeyError, RuntimeError) as exc:
        return local_suburb_matches(cleaned), str(exc)


@st.cache_data(ttl=15 * 60, show_spinner=False)
def load_saved_counts(
    suburb_rows: tuple[tuple[str, str], ...], source: str = OSM_SOURCE
) -> tuple[dict[str, int], str | None]:
    """Load saved feature counts only for the selected suburbs and their legacy names."""
    counts: dict[str, int] = {}
    try:
        for suburb, legacy_name in suburb_rows:
            aliases = [suburb]
            if legacy_name and legacy_name not in aliases:
                aliases.append(legacy_name)
            for alias in aliases:
                rows = supabase_request(
                    "GET",
                    "amenity_counts",
                    params={
                        "select": "suburb,category,place_count,source",
                        "suburb": f"eq.{alias}",
                        "category": f"eq.{CATEGORY}",
                        "source": f"eq.{source}",
                        "limit": "1",
                    },
                )
                if rows:
                    counts[suburb] = int(rows[0]["place_count"])
                    break
        return counts, None
    except (requests.RequestException, ValueError, KeyError, RuntimeError) as exc:
        return counts, str(exc)


@st.cache_data(ttl=24 * 60 * 60, show_spinner=False)
def load_osm_counts(
    bounds: tuple[tuple[str, float, float, float, float], ...],
    suburb_rows: tuple[tuple[str, str], ...],
    force_live: bool = False,
) -> tuple[dict[str, int] | None, str, str | None, str, str | None]:
    """Count four OSM leisure feature types within selected suburb bounding boxes."""
    fetched_at = datetime.now(timezone.utc).isoformat()
    if not force_live:
        saved_counts, _ = load_saved_counts(suburb_rows, source=OSM_SOURCE)
        if all(suburb in saved_counts for suburb, *_ in bounds):
            return saved_counts, fetched_at, None, "Supabase", None

    errors = []
    for endpoint in OVERPASS_ENDPOINTS:
        try:
            elements_by_id = {}
            for _, south, west, north, east in bounds:
                query = (
                    f'[out:json][timeout:25];\n'
                    f'nwr({south},{west},{north},{east})["leisure"~"^(park|garden|nature_reserve|playground)$"];\n'
                    "out center;"
                )
                response = session.post(
                    endpoint,
                    data={"data": query},
                    headers={
                        "User-Agent": "DemografyNeighbourhoodLivability/0.1 (Streamlit prototype)",
                        "Accept": "application/json",
                    },
                    timeout=60,
                )
                response.raise_for_status()
                for element in response.json().get("elements", []):
                    elements_by_id[(element.get("type"), element.get("id"))] = element

            counts = {suburb: set() for suburb, *_ in bounds}
            for element in elements_by_id.values():
                point = element.get("center", element)
                if "lat" not in point or "lon" not in point or element.get("tags", {}).get("leisure") not in OSM_LEISURE_TAGS:
                    continue
                identity = (element.get("type"), element.get("id"))
                for suburb, south, west, north, east in bounds:
                    if south <= point["lat"] <= north and west <= point["lon"] <= east:
                        counts[suburb].add(identity)
            live_counts = {suburb: len(ids) for suburb, ids in counts.items()}
            try:
                save_osm_counts(live_counts)
                sync_error = None
            except (requests.RequestException, ValueError, RuntimeError) as exc:
                sync_error = str(exc)
            return live_counts, fetched_at, None, "OpenStreetMap", sync_error
        except (requests.RequestException, ValueError, KeyError, TypeError) as exc:
            errors.append(f"{endpoint}: {exc}")

    return None, fetched_at, "Public Overpass endpoints failed. " + " | ".join(errors), "", None


def save_osm_counts(counts: dict[str, int]) -> None:
    """Upsert OSM feature counts calculated from CSV suburb extents."""
    rows = [
        {
            "suburb": suburb,
            "category": CATEGORY,
            "place_count": count,
            "source": OSM_SOURCE,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        for suburb, count in counts.items()
    ]
    supabase_request(
        "POST",
        "amenity_counts",
        params={"on_conflict": "suburb,category"},
        json=rows,
        prefer="resolution=merge-duplicates,return=minimal",
    )


def suburb_label(row: dict) -> str:
    name = row["suburb"]
    state = row.get("state_abbr")
    if not state or name.endswith(f", {state}") or f"({state})" in name or f"- {state})" in name:
        return name
    return f"{name} · {state}"


st.title("Neighbourhood Livability Index")
st.caption("Search Australian suburbs and compare mapped parks and nearby green/recreation features across a pair.")

if not all(supabase_config()):
    st.info("Supabase is not configured. Searching the bundled suburb CSV; live OSM counts still require an internet connection.")

left, right = st.columns(2)
query_a = left.text_input("Search first suburb", value="Chatswood, NSW", key="search_suburb_a")
query_b = right.text_input("Search second suburb", value="Newtown, NSW", key="search_suburb_b")
results_a, error_a = search_suburbs(query_a)
results_b, error_b = search_suburbs(query_b)

if error_a or error_b:
    st.warning(f"Could not search Supabase; using the bundled suburb CSV instead. Details: {error_a or error_b}")

selected_a = selected_b = None
left, right = st.columns(2)
if results_a:
    labels_a = {suburb_label(row): row for row in results_a}
    label_a = left.selectbox("Choose first suburb", list(labels_a), key="choose_suburb_a")
    selected_a = labels_a[label_a]
else:
    left.caption("Enter at least two letters to search.")
if results_b:
    labels_b = {suburb_label(row): row for row in results_b}
    label_b = right.selectbox("Choose second suburb", list(labels_b), key="choose_suburb_b")
    selected_b = labels_b[label_b]
else:
    right.caption("Enter at least two letters to search.")

compare_clicked = st.button("Compare selected suburbs", type="primary", disabled=not (selected_a and selected_b))
if compare_clicked and selected_a and selected_b:
    if selected_a["suburb"] == selected_b["suburb"]:
        st.warning("Choose two different suburbs to compare.")
    else:
        st.session_state["active_comparison"] = (selected_a, selected_b)

pair = st.session_state.get("active_comparison")
if not pair:
    st.info("Search for two suburbs and select **Compare selected suburbs** to load their Parks counts.")
    st.stop()

suburb_a, suburb_b = pair
try:
    bounds = tuple(
        (
            row["suburb"], float(row["min_lat"]), float(row["min_lon"]),
            float(row["max_lat"]), float(row["max_lon"]),
        )
        for row in pair
    )
except (KeyError, TypeError, ValueError):
    st.error("The selected suburb is missing CSV boundary coordinates. Re-import the suburb list using the setup steps in README.md.")
    st.stop()
osm_counts: dict[str, int] | None = None
osm_origin = ""
osm_sync_error: str | None = None
counts_by_suburb: dict[str, int] = {}
osm_legacy_fallback = False
legacy_rows = tuple((row["suburb"], row.get("legacy_name", "")) for row in pair)
force_live_osm = st.session_state.pop("force_live_osm", False)
try:
    with st.spinner(f"Loading OpenStreetMap feature counts for {suburb_a['suburb']} and {suburb_b['suburb']}…"):
        osm_counts, osm_fetched_at, osm_error, osm_origin, osm_sync_error = load_osm_counts(
            bounds, legacy_rows, force_live=force_live_osm
        )
except (requests.RequestException, ValueError, KeyError, TypeError) as exc:
    osm_counts, osm_fetched_at, osm_error, osm_origin = None, datetime.now(timezone.utc).isoformat(), str(exc), ""

if osm_counts is not None:
    counts_by_suburb = osm_counts
    if osm_origin == "Supabase":
        st.caption("OSM green/recreation feature counts loaded from Supabase · CSV bounding-box method · © OpenStreetMap contributors")
    else:
        fetched_time = datetime.fromisoformat(osm_fetched_at).astimezone().strftime("%d %b %Y %H:%M %Z")
        st.caption(f"OpenStreetMap count inside CSV bounding boxes · leisure=park, garden, nature_reserve and playground · fetched {fetched_time} · © OpenStreetMap contributors")
        if osm_sync_error:
            st.warning(f"Live OSM counts loaded, but they could not be synced to Supabase: {osm_sync_error}")
else:
    st.warning(f"Could not load live OSM counts for this pair. Checking saved Supabase OSM counts. Details: {osm_error}")
    counts_by_suburb, saved_error = load_saved_counts(legacy_rows, source=OSM_SOURCE)
    if saved_error:
        st.caption(f"Supabase count lookup also failed: {saved_error}")
    if not counts_by_suburb:
        counts_by_suburb, legacy_error = load_saved_counts(legacy_rows, source="osm_overpass")
        osm_legacy_fallback = bool(counts_by_suburb)
        if legacy_error:
            st.caption(f"Legacy Supabase count lookup also failed: {legacy_error}")
        if osm_legacy_fallback:
            st.warning("Showing saved legacy circular park-only counts. These do not use the CSV bounding boxes or four-tag definition; refresh live OSM data for comparable current results.")
    elif counts_by_suburb:
        st.caption("Showing saved Supabase counts from the CSV bounding-box method.")

if st.button("Refresh live OSM counts", help="Bypass cached and saved counts, query OSM within the selected CSV bounding boxes, then sync successful results to Supabase."):
    load_osm_counts.clear()
    load_saved_counts.clear()
    st.session_state["force_live_osm"] = True
    st.rerun()

if any(row["suburb"] not in counts_by_suburb for row in pair):
    st.error("No current boundary-based OSM count is available for this suburb pair. Retry the request or check Overpass availability.")
    if st.button("Retry OSM request"):
        load_osm_counts.clear()
        st.rerun()
    st.stop()

count_label = "Parks and green/recreation features" if not osm_legacy_fallback else "Parks (legacy fallback)"
st.subheader(f"{count_label} Density Score")
st.write("Distinct OSM features tagged park, garden, nature reserve or playground whose representative point falls within the selected suburb’s CSV longitude/latitude bounding box. Density uses the supplied SAL area_km2.")
st.caption("The rectangle is an extent approximation, not the actual SAL polygon. Its feature count may include places outside the suburb; area_km2 is the supplied SAL area. Scores are benchmarked against the higher density in this selected pair.")

count_a = counts_by_suburb[suburb_a["suburb"]]
count_b = counts_by_suburb[suburb_b["suburb"]]
density_a = count_a / float(suburb_a["area_km2"])
density_b = count_b / float(suburb_b["area_km2"])
benchmark_density = max(density_a, density_b)
score_a = min(100, 100 * density_a / benchmark_density) if benchmark_density else 0
score_b = min(100, 100 * density_b / benchmark_density) if benchmark_density else 0
rows = [{
    "Category": count_label,
    f"{suburb_a['suburb']} count": count_a,
    f"{suburb_a['suburb']} area (km²)": round(float(suburb_a["area_km2"]), 2),
    f"{suburb_a['suburb']} / km²": round(density_a, 1),
    f"{suburb_a['suburb']} score": round(score_a),
    f"{suburb_b['suburb']} count": count_b,
    f"{suburb_b['suburb']} area (km²)": round(float(suburb_b["area_km2"]), 2),
    f"{suburb_b['suburb']} / km²": round(density_b, 1),
    f"{suburb_b['suburb']} score": round(score_b),
}]
overall_a, overall_b = round(score_a), round(score_b)

col_a, col_b = st.columns(2)
col_a.metric(f"{suburb_a['suburb']} · density score", f"{overall_a}/100")
col_b.metric(
    f"{suburb_b['suburb']} · density score",
    f"{overall_b}/100",
    delta=f"{overall_b - overall_a:+} points vs {suburb_a['suburb']}",
)
st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True)

st.subheader("Buyer snapshot")
scorecard_data = pd.DataFrame([
    {"Suburb": suburb_a["suburb"], "Score": overall_a},
    {"Suburb": suburb_b["suburb"], "Score": overall_b},
])
if overall_a > overall_b:
    leading_suburb, trailing_suburb = suburb_a["suburb"], suburb_b["suburb"]
elif overall_b > overall_a:
    leading_suburb, trailing_suburb = suburb_b["suburb"], suburb_a["suburb"]
else:
    leading_suburb = trailing_suburb = None
if leading_suburb:
    st.success(f"{leading_suburb} has a {count_label.lower()} density score {abs(overall_a - overall_b)} points higher than {trailing_suburb}.")
else:
    st.info("The two suburbs are tied on the current Parks density score.")

score_colors = [leading_suburb or suburb_a["suburb"], trailing_suburb or suburb_b["suburb"]]
score_bars = alt.Chart(scorecard_data).mark_bar(height=34, cornerRadiusEnd=7).encode(
    y=alt.Y("Suburb:N", sort=alt.SortField(field="Score", order="descending"), title=None),
    x=alt.X("Score:Q", title=f"{count_label} density score", scale=alt.Scale(domain=[0, 110], nice=False), axis=alt.Axis(values=[0, 25, 50, 75, 100])),
    color=alt.Color("Suburb:N", scale=alt.Scale(domain=score_colors, range=["#8B5CF6", "#CBD0E0"]), legend=None),
    tooltip=[alt.Tooltip("Suburb:N"), alt.Tooltip("Score:Q", format=".0f", title="Score out of 100")],
)
score_labels = alt.Chart(scorecard_data).mark_text(align="left", baseline="middle", dx=8, fontWeight="bold", color="#171A2E").encode(
    y=alt.Y("Suburb:N", sort=alt.SortField(field="Score", order="descending")),
    x=alt.X("Score:Q", scale=alt.Scale(domain=[0, 110], nice=False)),
    text=alt.Text("Score:Q", format=".0f"),
)
st.altair_chart((score_bars + score_labels).properties(height=135), use_container_width=True)
st.caption(f"CSV boundary-area score: {count_label.lower()} per km², benchmarked to the higher-density suburb in this pair.")

with st.expander("KPI method and limitations"):
    st.markdown(
        """- **OpenStreetMap count:** distinct features tagged `leisure=park`, `leisure=garden`, `leisure=nature_reserve` or `leisure=playground` whose representative point falls inside the CSV `min_lat`, `min_lon`, `max_lat`, `max_lon` extent. Deduplicated by OSM element type and ID; separately mapped features within the same park may each count.
- **Density:** count ÷ the CSV `area_km2` value for the suburb.
- **Benchmark:** higher Parks density within the selected pair.
- **Parks density score:** `min(100, suburb Parks density ÷ pair benchmark density × 100)`.

CSV bounds form rectangles, not exact SAL polygons. The box can include locations outside the suburb, while `area_km2` is the true supplied SAL area; treat density as an indicative comparison. Counts are cached for 24 hours."""
    )

st.divider()
st.caption("Demografy wireframe prototype · OSM coverage varies by location · © OpenStreetMap contributors")
