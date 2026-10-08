"""Sample-data Streamlit demo for suburb amenity density comparison."""

from __future__ import annotations

import math
import pandas as pd
import streamlit as st


st.set_page_config(page_title="Demografy | Neighbourhood comparison", page_icon="⌂", layout="wide")

RADIUS_KM = 1.0
CATCHMENT_KM2 = math.pi * RADIUS_KM**2
CATEGORIES = ["Cafes", "Parks", "Wellness", "Childcare", "Transport"]

# Illustrative fixture counts only. Replace with cached, validated Google Places data.
SAMPLE_COUNTS = {
    "Parramatta, NSW": {"Cafes": 28, "Parks": 15, "Wellness": 18, "Childcare": 12, "Transport": 30},
    "Chatswood, NSW": {"Cafes": 45, "Parks": 22, "Wellness": 25, "Childcare": 20, "Transport": 40},
    "Newtown, NSW": {"Cafes": 38, "Parks": 11, "Wellness": 23, "Childcare": 9, "Transport": 34},
}

st.title("Neighbourhood Livability Index")
st.caption("Compare everyday amenity density across two suburbs.")

with st.form("suburb_comparison"):
    left, right = st.columns(2)
    suburb_a = left.selectbox("First suburb", list(SAMPLE_COUNTS), index=0)
    suburb_b = right.selectbox("Second suburb", list(SAMPLE_COUNTS), index=1)
    submitted = st.form_submit_button("Compare suburbs", type="primary")

if suburb_a == suburb_b:
    st.warning("Choose two different suburbs to compare.")
    st.stop()

st.info("Demo uses illustrative test data. Live Google Places and Supabase connections are not configured.")

st.subheader("Daily Needs Amenity Density Score")
st.write("Distinct places within a 1 km straight-line radius of each suburb centre, divided by the catchment area.")
st.caption(f"Catchment area: π × {RADIUS_KM:.0f}² = {CATCHMENT_KM2:.2f} km² · Prototype scores are relative to this suburb pair.")

rows = []
for category in CATEGORIES:
    count_a = SAMPLE_COUNTS[suburb_a][category]
    count_b = SAMPLE_COUNTS[suburb_b][category]
    density_a = count_a / CATCHMENT_KM2
    density_b = count_b / CATCHMENT_KM2
    max_density = max(density_a, density_b)
    score_a = 100 * density_a / max_density if max_density else 0
    score_b = 100 * density_b / max_density if max_density else 0
    rows.append({
        "Category": category,
        f"{suburb_a} count": count_a,
        f"{suburb_a} / km²": round(density_a, 1),
        f"{suburb_a} score": round(score_a),
        f"{suburb_b} count": count_b,
        f"{suburb_b} / km²": round(density_b, 1),
        f"{suburb_b} score": round(score_b),
    })

scores_a = [row[f"{suburb_a} score"] for row in rows]
scores_b = [row[f"{suburb_b} score"] for row in rows]
overall_a = round(sum(scores_a) / len(scores_a))
overall_b = round(sum(scores_b) / len(scores_b))

col_a, col_b = st.columns(2)
col_a.metric(f"{suburb_a} · density score", f"{overall_a}/100")
col_b.metric(f"{suburb_b} · density score", f"{overall_b}/100", delta=f"{overall_b - overall_a:+} points vs {suburb_a}")

st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True)
chart_data = pd.DataFrame({
    "Category": CATEGORIES,
    suburb_a: [row[f"{suburb_a} score"] for row in rows],
    suburb_b: [row[f"{suburb_b} score"] for row in rows],
}).set_index("Category")
st.bar_chart(chart_data, horizontal=True, x_label="Relative category score (0–100)", y_label="Category")

with st.expander("KPI method and limitations"):
    st.markdown(
        """- **Count:** distinct matching places, deduplicated by Place ID.
- **Density:** count ÷ 3.14 km².
- **Category score:** category density ÷ the higher density in this comparison × 100.
- **Overall score:** simple mean of the five category scores.

This is a prototype density comparison, not a 15-minute walking-access score. A production version needs agreed suburb centres, verified place-type mappings, a stable metro/state benchmark, and live API/cache integration."""
    )

st.divider()
st.caption("Demografy wireframe prototype · sample values are illustrative, not live market data")
