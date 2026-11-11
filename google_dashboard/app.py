"""Streamlit entry point for the Neighbourhood Livability Index."""

import os
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from time import monotonic

import altair as alt
import pandas as pd
import psycopg
import streamlit as st

from google_dashboard.outdoor_analysis import (
    benchmark_candidates, discover_places, load_benchmark, rating,
)
from google_dashboard.pipeline import PARKS_KPI, PipelineError, Suburb, get_metrics, load_catalog

from livability.weighting import PARKS_MEASURES, personal_score, suggest_weights

PALETTE = ["#7045CB", "#3E2C64"]
DEMO_SUBURBS = [
    Suburb("demo-bondi", "Bondi", "NSW", "2026", 1.1, None, -33.90, 151.25, -33.88, 151.28),
    Suburb("demo-newtown", "Newtown", "NSW", "2042", 1.6, None, -33.91, 151.17, -33.89, 151.19),
]
DEMO_COUNTS = [8, 6]


def setting(name):
    value = os.environ.get(name)
    if value is not None:
        return value.strip()
    try:
        return str(st.secrets.get(name, "")).strip()
    except FileNotFoundError:
        return ""


@st.cache_data(ttl=900, max_entries=4, show_spinner=False)
def suburb_catalog(database_url):
    return load_catalog(database_url)


def compare(suburbs, database_url, api_key, demo):
    if demo:
        return [
            {"counts": {PARKS_KPI: DEMO_COUNTS[DEMO_SUBURBS.index(suburb)]},
             "source": "Demo data", "refreshed_at": None}
            for suburb in suburbs
        ]

    progress = st.progress(0, text="Processing… checking for parks and outdoor places")
    deadline = monotonic() + 12
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            pending = {
                pool.submit(get_metrics, database_url, api_key, suburb, deadline): suburb
                for suburb in suburbs
            }
            results = {}
            for completed in as_completed(pending):
                suburb = pending[completed]
                try:
                    results[suburb] = completed.result()
                except PipelineError as error:
                    results[suburb] = str(error)
                progress.progress(len(results) / len(suburbs), text="Processing… preparing the comparison")
        errors = [f"{suburb.label} — {results[suburb]}" for suburb in suburbs if isinstance(results[suburb], str)]
        if errors:
            raise PipelineError("\n\n".join(errors))
        return [results[suburb] for suburb in suburbs]
    finally:
        progress.empty()


def render_comparison(suburbs, results, labels, demo, database_url, groq_key, cohort):
    names = [labels.get(suburb, suburb.label) for suburb in suburbs]
    counts = [result["counts"][PARKS_KPI] for result in results]
    densities = [count / suburb.area_km2 for count, suburb in zip(counts, suburbs, strict=True)]
    benchmark, benchmark_suburb, sample_size, count_reference = None, None, 0, None
    if not demo:
        try:
            benchmark, benchmark_suburb, sample_size, count_reference = load_benchmark(database_url, cohort)
        except psycopg.Error:
            st.warning("The outdoor benchmark is temporarily unavailable.")

    st.header(PARKS_KPI)
    with st.container(horizontal=True):
        for name, count, result in zip(names, counts, results, strict=True):
            refreshed = result["refreshed_at"]
            source = result["source"]
            if refreshed is not None:
                source += f" · {refreshed:%d %b %Y}"
            st.metric(name, count, delta=source, delta_color="off", border=True)

    with st.container(border=True):
        chart_data = pd.DataFrame({"Suburb": names, "Places found": counts})
        chart = alt.Chart(chart_data).mark_bar(cornerRadiusEnd=4).encode(
            x=alt.X("Places found:Q", axis=alt.Axis(tickMinStep=1)),
            y=alt.Y("Suburb:N", sort=names, title=None),
            color=alt.Color(
                "Suburb:N", scale=alt.Scale(domain=names, range=PALETTE),
                legend=None,
            ),
            tooltip=["Suburb:N", "Places found:Q"],
        ).properties(height=120)
        st.altair_chart(chart, alt="Parks and outdoor places found in each suburb")
        if not demo:
            st.caption("**Google Maps** · Up to 60 results per suburb. Rectangular search bounds can include places in nearby suburbs.")

    st.subheader("Outdoor places per km²")
    with st.container(horizontal=True):
        for name, density in zip(names, densities, strict=True):
            grade = rating(100 * density / benchmark) if benchmark else None
            st.metric(name, f"{density:.2f}", delta=grade, delta_color="off", border=True)
    if benchmark:
        st.caption(f"100-point benchmark · {benchmark_suburb} · {benchmark:.2f} places per km². Highest of {sample_size} sampled suburbs outside CBDs.")
    elif not demo:
        st.caption(f"Benchmark sample · {sample_size} of 12 suburbs have fresh results. The highest density sets 100.")

    render_preferences(names, counts, densities, benchmark, count_reference, groq_key)

    with st.container(border=True):
        st.subheader("Suburb locations")
        points = pd.DataFrame([
            {
                "latitude": (suburb.min_lat + suburb.max_lat) / 2,
                "longitude": (suburb.min_lon + suburb.max_lon) / 2,
                "colour": colour,
            }
            for suburb, colour in zip(suburbs, PALETTE, strict=True)
        ])
        st.map(points, color="colour", size=60, height=340, alt="Midpoints of both suburb bounding rectangles")
        st.caption(f"Violet · {names[0]}   |   Deep plum · {names[1]} · Markers show the midpoints of the CSV bounds.")


def render_preferences(names, counts, densities, benchmark, count_reference, groq_key):
    with st.expander("Personalise your parks comparison", expanded=True):
        preferences = st.text_input(
            "What matters to you outdoors?",
            placeholder="I have a toddler and no car.",
            max_chars=500,
            help="With Groq configured, submitting sends this text to Groq. Avoid personal details.",
        )
        if st.button("Suggest KPI weights"):
            with st.spinner("Suggesting weights…"):
                suggestion = suggest_weights(preferences, groq_key, kpis=PARKS_MEASURES)
            for key, value in suggestion.weights.items():
                st.session_state[f"outdoor_weight_{key}"] = value
            st.session_state.outdoor_suggestion = suggestion
        suggestion = st.session_state.get("outdoor_suggestion")
        if suggestion:
            st.caption({"ai": "Groq suggestion", "keywords": "Keyword suggestion",
                        "default": "Default weights"}[suggestion.source])
        weights = {}
        for key, label in (("parks_total", "Total places"), ("parks", "Places per km²")):
            widget_key = f"outdoor_weight_{key}"
            st.session_state.setdefault(widget_key, 3)
            weights[key] = st.slider(label, 0, 5, key=widget_key)
            if suggestion and suggestion.reasons.get(key):
                st.caption(suggestion.reasons[key])
        if not (benchmark and count_reference):
            st.caption("Personal scores are available when the benchmark sample is complete.")
        elif not any(weights.values()):
            st.caption("Set at least one weight above zero to see personal scores.")
        else:
            st.subheader("Personal parks score")
            with st.container(horizontal=True):
                for name, count, density in zip(names, counts, densities, strict=True):
                    score = personal_score({
                        "parks_total": min(100, 100 * count / count_reference),
                        "parks": min(100, 100 * density / benchmark),
                    }, weights)
                    st.metric(name, f"{score}/100", delta=rating(score), delta_color="off", border=True)
            st.caption(f"100-point references · {count_reference} total places and {benchmark:.2f} places per km².")


st.set_page_config(page_title="Neighbourhood Livability Index", page_icon=":material/location_on:", layout="centered")
st.html("""
    <style>
        .st-key-livability_hero {
            background: linear-gradient(135deg, #161325, #35224e 68%, #513477);
            border-radius: 1rem;
            padding: clamp(1.25rem, 4vw, 2.75rem);
        }
        .st-key-livability_hero h1 {
            color: #fcfaff;
            letter-spacing: -0.035em;
        }
        .st-key-livability_hero p {
            color: #e8dcfa;
        }
    </style>
""")
with st.container(key="livability_hero"):
    st.title("Neighbourhood Livability Index", anchor=False)
    st.write("Compare parks and outdoor places across Australian suburbs.")

database_url = setting("SUPABASE_DB_URL")
api_key = setting("GOOGLE_PLACES_API_KEY")
groq_key = setting("GROQ_API_KEY")
demo = setting("LIVABILITY_DEMO").lower() in {"1", "true"}
if demo:
    st.info("Demo mode uses sample counts for parks and outdoor places.")
    catalog = DEMO_SUBURBS
else:
    if not (database_url and api_key):
        missing = [
            name for name, value in (
                ("SUPABASE_DB_URL", database_url),
                ("GOOGLE_PLACES_API_KEY", api_key),
            ) if not value
        ]
        st.info(f"Live data setup requires {', '.join(missing)} in Streamlit secrets. See README.md for setup.")
        st.stop()
    try:
        with st.spinner("Loading suburbs…"):
            catalog = suburb_catalog(database_url)
    except psycopg.Error:
        st.error("Supabase could not load the suburb catalogue. Check the connection, imported CSV columns and permissions.")
        st.stop()

if len(catalog) < 2:
    st.warning("At least two suburbs with valid bounds and areas are required.")
    st.stop()

duplicates = Counter(suburb.label for suburb in catalog)
labels = {
    suburb: f"{suburb.label} · {suburb.sal_code}" if duplicates[suburb.label] > 1 else suburb.label
    for suburb in catalog
}
with st.form("suburb_comparison"):
    first_col, second_col = st.columns(2)
    with first_col:
        first = st.selectbox("First suburb", catalog, format_func=labels.__getitem__, index=0 if demo else None, placeholder="Search suburb name or postcode")
    with second_col:
        second = st.selectbox("Second suburb", catalog, format_func=labels.__getitem__, index=1 if demo else None, placeholder="Search suburb name or postcode")
    submitted = st.form_submit_button("Compare suburbs", type="primary", icon=":material/compare_arrows:")

if submitted:
    st.session_state.pop("parks_comparison", None)
    if first is None or second is None:
        st.warning("Choose two suburbs from the catalogue.")
    elif first == second:
        st.warning("Choose two different suburbs.")
    else:
        selected = (first, second)
        try:
            st.session_state.parks_comparison = (selected, compare(selected, database_url, api_key, demo))
        except PipelineError as error:
            st.error(str(error))

if "parks_comparison" in st.session_state:
    selected, results = st.session_state.parks_comparison
    render_comparison(selected, results, labels, demo, database_url, groq_key, benchmark_candidates(catalog))

if groq_key:
    with st.expander("Discover outdoor places across Australia"):
        interest = st.text_input("Outdoor interests or region (optional)", max_chars=300)
        if st.button("Search for popular places"):
            st.session_state.pop("outdoor_discovery", None)
            try:
                with st.spinner("Searching Australian parks and tourism sources…"):
                    st.session_state.outdoor_discovery = discover_places(
                        groq_key, interest.strip() or "Popular parks and outdoor attractions across Australia"
                    )
            except ValueError as error:
                st.error(str(error))
        if st.session_state.get("outdoor_discovery"):
            st.markdown(st.session_state.outdoor_discovery)
