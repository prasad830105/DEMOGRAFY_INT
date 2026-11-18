"""Streamlit entry point for the Neighbourhood Livability Index."""

import os
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from time import monotonic

import altair as alt
import pandas as pd
import psycopg
import streamlit as st

from boundary_store import ensure_boundary_measurement
from google_boundary_pilot import BoundaryError
from outdoor_analysis import (
    benchmark_candidates, benchmark_score, load_benchmark, outdoor_score_components, rating,
    suggest_weight, weighted_outdoor_score,
)
from pipeline import PARKS_KPI, SEARCH_TIMEOUT_SECONDS, PipelineError, Suburb, connect, get_metrics, load_catalog

PALETTE = ["#7045CB", "#3E2C64"]
KPI_HEADING = "Parks and Outdoor Spaces"
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
    deadline = monotonic() + SEARCH_TIMEOUT_SECONDS
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


def render_score_cards(names, values, grades, value_format, section):
    leader = None
    if len(values) == 2 and None not in values and values[0] != values[1]:
        leader = int(values[1] > values[0])

    for index, (column, name, value, grade) in enumerate(zip(st.columns(len(names)), names, values, grades, strict=True)):
        highlight = index == leader
        with column.container(border=True, key=f"{section}_leader" if highlight else None):
            detail = " · ".join(filter(None, ("Higher score" if highlight else None, grade)))
            st.metric(name, value_format.format(value) if value is not None else "Unavailable",
                      delta=detail or None, delta_color="off", delta_arrow="off")
    return leader


def render_comparison(suburbs, results, labels, demo, database_url, groq_key, cohort):
    names = [labels.get(suburb.sal_code, suburb.label) for suburb in suburbs]
    counts = [result["counts"][PARKS_KPI] for result in results]
    densities = [count / suburb.area_km2 for count, suburb in zip(counts, suburbs, strict=True)]
    benchmark, benchmark_suburb, sample_size, count_reference = None, None, 0, None
    if demo:
        demo_densities = [count / suburb.area_km2 for count, suburb in zip(DEMO_COUNTS, DEMO_SUBURBS, strict=True)]
        benchmark = max(demo_densities)
        benchmark_suburb = DEMO_SUBURBS[demo_densities.index(benchmark)].label
        sample_size = len(DEMO_SUBURBS)
        count_reference = max(DEMO_COUNTS)
    else:
        try:
            benchmark, benchmark_suburb, sample_size, count_reference = load_benchmark(database_url, cohort)
        except psycopg.Error:
            st.warning("The outdoor benchmark is temporarily unavailable.")

    st.header(KPI_HEADING)
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
        st.altair_chart(chart, alt="Parks and outdoor spaces found in each suburb")
        if not demo:
            st.caption("**Google Maps** · Busy search areas are split at 60 results. The suburb rectangle can include nearby places.")

    capped = [name for name, result in zip(names, results, strict=True) if result.get("search_capped")]
    if capped:
        st.warning(f"The count for {', '.join(capped)} may be incomplete. A smallest search area reached Google's result limit.")

    if benchmark:
        st.subheader(f"{KPI_HEADING} score out of 100")
        scores = [round(benchmark_score(density, benchmark), 1) for density in densities]
        render_score_cards(names, scores, [rating(score) for score in scores], "{:.1f}/100", "benchmark")

    st.subheader("Outdoor places per km²")
    displayed_densities = [round(density, 2) for density in densities]
    leader = render_score_cards(names, displayed_densities, [None] * len(names), "{:.2f}", "density")
    if leader is None:
        st.markdown(f"Both suburbs are tied at **{displayed_densities[0]:.2f} outdoor places per km²**.")
    else:
        other = 1 - leader
        st.markdown(
            f"**{names[leader]}** is the better choice for parks density, with **{displayed_densities[leader]:.2f}** "
            f"outdoor places per km² compared with **{displayed_densities[other]:.2f}** in {names[other]}."
        )
    if demo:
        st.caption(f"Demo benchmark · {benchmark_suburb} · {benchmark:.2f} places per km².")
    elif benchmark:
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


def refresh_boundary_comparison(suburbs, database_url, aggregate_key):
    with ThreadPoolExecutor(max_workers=2) as pool:
        pending = {
            pool.submit(ensure_boundary_measurement, database_url, aggregate_key, suburb): suburb
            for suburb in suburbs
        }
        errors = {}
        for completed in as_completed(pending):
            suburb = pending[completed]
            try:
                error = completed.result()
            except BoundaryError as failure:
                error = str(failure)
            if error:
                errors[suburb] = error
    return errors


def render_boundary_comparison(suburbs, labels, database_url, groq_key, errors):
    try:
        with connect(database_url) as connection:
            rows = connection.execute("""
                select benchmark.benchmark_name, benchmark.measured_suburbs, benchmark.catalogue_suburbs,
                       scores.sal_code, scores.density_score, scores.total_score
                from livability.current_boundary_benchmark as benchmark
                left join livability.current_boundary_scores as scores on scores.sal_code = any(%s)
            """, ([suburb.sal_code for suburb in suburbs],)).fetchall()
    except psycopg.Error:
        st.warning("The ABS boundary scores are temporarily unavailable.")
        return

    st.header(KPI_HEADING)
    names = [labels.get(suburb.sal_code, suburb.label) for suburb in suburbs]
    for suburb, name in zip(suburbs, names, strict=True):
        if suburb in errors:
            st.warning(f"{name} — {errors[suburb]}")
    if not rows:
        st.info("The benchmark needs a fresh measurement with a positive parks density outside CBDs.")
        return

    scores = {row["sal_code"]: row for row in rows if row["sal_code"] is not None}
    densities = [scores.get(suburb.sal_code, {}).get("density_score") for suburb in suburbs]
    grades = [rating(score) if score is not None else None for score in densities]
    leader = render_score_cards(names, densities, grades, "{}/100", "density")
    if None in densities:
        st.caption("Both suburbs need a score for a recommendation.")
    elif leader is None:
        st.markdown(f"Both suburbs are in the same parks density score band at **{densities[0]}/100**.")
    else:
        other = 1 - leader
        st.markdown(
            f"**{names[leader]}** is the better choice for parks density. Its higher concentration of outdoor places "
            f"per km² earned **{densities[leader]}/100**, compared with **{densities[other]}/100** for {names[other]}."
        )

    benchmark = rows[0]
    st.caption(
        f"100-point benchmark · {benchmark['benchmark_name']} · Highest measured density outside CBDs. "
        f"Coverage {benchmark['measured_suburbs']:,}/{benchmark['catalogue_suburbs']:,} suburbs."
    )
    st.caption("Google Maps · Parks, national parks, playgrounds and gardens matched to ABS suburb polygons.")
    measured = [suburb for suburb in suburbs if suburb.sal_code in scores]
    if measured:
        render_preferences(
            [labels.get(suburb.sal_code, suburb.label) for suburb in measured],
            [scores[suburb.sal_code]["total_score"] for suburb in measured],
            [scores[suburb.sal_code]["density_score"] for suburb in measured],
            100, 100, groq_key, score_bands=True,
        )


def render_preferences(names, counts, densities, benchmark, count_reference, groq_key, *, score_bands=False):
    with st.expander("Personalise your parks comparison", expanded=True):
        if groq_key:
            preferences = st.text_input(
                "What matters to you outdoors?",
                placeholder="I prefer a suburb with more parks packed into a smaller area.",
                max_chars=500,
            )
            if st.button("Suggest KPI weights"):
                if not preferences.strip():
                    st.warning("Describe what matters to you first.")
                else:
                    try:
                        with st.spinner("Suggesting weights…"):
                            weight, explanation = suggest_weight(groq_key, preferences.strip())
                        st.session_state.outdoor_total_weight = weight
                        st.session_state.outdoor_weight_explanation = explanation
                    except ValueError as error:
                        st.error(str(error))
        st.session_state.setdefault("outdoor_total_weight", 50)
        total_weight = st.slider("Total places weight (%)", 0, 100, step=5, key="outdoor_total_weight")
        st.caption(f"Places per km² weight · {100 - total_weight}%")
        if st.session_state.get("outdoor_weight_explanation"):
            st.caption(f"AI suggestion · {st.session_state.outdoor_weight_explanation}")
        if benchmark and count_reference:
            st.subheader(f"Personalised {KPI_HEADING} score")
            scores = [
                weighted_outdoor_score(count, density, count_reference, benchmark, total_weight)
                for count, density in zip(counts, densities, strict=True)
            ]
            displayed_scores = [round(score, 1) for score in scores]
            leader = render_score_cards(names, displayed_scores, [rating(score) for score in displayed_scores],
                                        "{:.1f}/100", "personal")
            if leader is not None:
                other = 1 - leader
                winner_total, winner_density = outdoor_score_components(
                    counts[leader], densities[leader], count_reference, benchmark,
                )
                other_total, other_density = outdoor_score_components(
                    counts[other], densities[other], count_reference, benchmark,
                )
                total_advantage = (winner_total - other_total) * total_weight
                density_advantage = (winner_density - other_density) * (100 - total_weight)
                drivers = [label for label, advantage in (
                    ("total outdoor places", total_advantage), ("outdoor places per km²", density_advantage),
                ) if advantage > 0]
                st.markdown(
                    f"**{names[leader]}** is the better match for your weights, scoring **{displayed_scores[leader]:.1f}/100** "
                    f"to **{displayed_scores[other]:.1f}/100**. It has a higher score for {' and '.join(drivers)}."
                )
            elif len(displayed_scores) == 2:
                st.markdown(f"With your weights, both suburbs score **{displayed_scores[0]:.1f}/100**.")
            if score_bands:
                st.caption("The weights combine the total-places and density scores, each rounded down in five-point steps.")
            else:
                st.caption(f"100-point references · {count_reference} total places and {benchmark:.2f} places per km².")
        else:
            st.caption("Personalised scores are available when the benchmark sample is complete.")


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
        .st-key-density_leader, .st-key-benchmark_leader, .st-key-personal_leader {
            background-color: #F6F1FC;
            outline: 1px solid #7045CB;
            outline-offset: -1px;
            border-radius: 0.5rem;
        }
    </style>
""")
with st.container(key="livability_hero"):
    st.title("Neighbourhood Livability Index", anchor=False)
    st.write("Compare parks and outdoor places across Australian suburbs.")

database_url = setting("SUPABASE_DB_URL")
api_key = setting("GOOGLE_PLACES_API_KEY")
aggregate_key = setting("GOOGLE_PLACES_AGGREGATE_API_KEY") or api_key
groq_key = setting("GROQ_API_KEY")
demo = setting("LIVABILITY_DEMO").lower() in {"1", "true"}
if demo:
    st.info("Demo mode uses sample counts for parks and outdoor places.")
    catalog = DEMO_SUBURBS
else:
    if not database_url:
        st.info("Live data setup requires SUPABASE_DB_URL in Streamlit secrets. See README.md for setup.")
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
    suburb.sal_code: f"{suburb.label} · {suburb.sal_code}" if duplicates[suburb.label] > 1 else suburb.label
    for suburb in catalog
}
use_aggregate = not demo and st.toggle(
    "Enable Places Aggregate API",
    value=False,
    key="use_places_aggregate",
    help="Turn on to compare using exact ABS suburb boundaries. Turn off to use Places API (New) Text Search.",
)
with st.form("suburb_comparison"):
    first_col, second_col = st.columns(2)
    with first_col:
        first = st.selectbox("First suburb", catalog, format_func=lambda suburb: labels[suburb.sal_code], index=0 if demo else None, placeholder="Search suburb name or postcode")
    with second_col:
        second = st.selectbox("Second suburb", catalog, format_func=lambda suburb: labels[suburb.sal_code], index=1 if demo else None, placeholder="Search suburb name or postcode")
    submitted = st.form_submit_button("Compare suburbs", type="primary", icon=":material/compare_arrows:")

if submitted:
    st.session_state.pop("parks_comparison", None)
    st.session_state.pop("boundary_comparison_result", None)
    if first is None or second is None:
        st.warning("Choose two suburbs from the catalogue.")
    elif first == second:
        st.warning("Choose two different suburbs.")
    else:
        selected = (first, second)
        try:
            if use_aggregate:
                with st.spinner("Checking Supabase and fetching any missing measurements…"):
                    errors = refresh_boundary_comparison(selected, database_url, aggregate_key)
                st.session_state.boundary_comparison_result = (selected, errors)
            else:
                if not demo and not api_key:
                    raise PipelineError("Set GOOGLE_PLACES_API_KEY to use the rectangular search.")
                st.session_state.parks_comparison = (selected, compare(selected, database_url, api_key, demo))
        except PipelineError as error:
            st.error(str(error))

if use_aggregate and "boundary_comparison_result" in st.session_state:
    selected, errors = st.session_state.boundary_comparison_result
    render_boundary_comparison(selected, labels, database_url, groq_key, errors)

if not use_aggregate and "parks_comparison" in st.session_state:
    selected, results = st.session_state.parks_comparison
    render_comparison(selected, results, labels, demo, database_url, groq_key, benchmark_candidates(catalog))
