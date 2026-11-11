"""Test three ABS suburb polygons with Google Places Aggregate."""

import requests
import streamlit as st

ABS_URL = "https://geo.abs.gov.au/arcgis/rest/services/ASGS2021/SAL/MapServer/0/query"
GOOGLE_URL = "https://areainsights.googleapis.com/v1:computeInsights"
PILOT = {"12969": "Newtown, NSW", "20495": "Carlton, VIC", "32587": "South Brisbane, QLD"}


def coordinates_for_google(geometry):
    rings = geometry["coordinates"]
    if geometry["type"] == "MultiPolygon" and len(rings) == 1:
        rings = rings[0]
    elif geometry["type"] != "Polygon":
        raise ValueError("Google custom areas require a single polygon.")
    if len(rings) != 1:
        raise ValueError("Google custom areas require a polygon without holes.")
    ring = rings[0]
    if len(ring) < 4 or ring[0] != ring[-1]:
        raise ValueError("The ABS polygon must be a closed ring.")
    origin_x, origin_y = ring[0]
    offsets = [(x - origin_x, y - origin_y) for x, y in ring]
    signed_area = sum(x1*y2 - x2*y1 for (x1,y1), (x2,y2) in zip(offsets, offsets[1:]))
    if signed_area == 0:
        raise ValueError("The ABS polygon has no area.")
    if signed_area < 0:
        ring = list(reversed(ring))
    return [{"latitude": lat, "longitude": lon} for lon, lat in ring]


def main():
    api_key = st.secrets["GOOGLE_PLACES_API_KEY"]
    ids = ", ".join(f"'{code}'" for code in PILOT)
    response = requests.get(ABS_URL, params={
        "where": f"SAL_CODE_2021 IN ({ids})",
        "outFields": "SAL_CODE_2021",
        "returnGeometry": "true",
        "outSR": "4326",
        "f": "geojson",
    }, timeout=15)
    response.raise_for_status()
    features = {str(f["properties"]["sal_code_2021"]): f["geometry"]
                for f in response.json()["features"]}
    if features.keys() != PILOT.keys():
        raise SystemExit("ABS did not return all three pilot boundaries.")
    for code, suburb in PILOT.items():
        try:
            coordinates = coordinates_for_google(features[code])
        except ValueError as error:
            print(f"{suburb}: {error}", flush=True)
            continue
        response = requests.post(GOOGLE_URL, headers={"X-Goog-Api-Key": api_key}, json={
            "insights": ["INSIGHT_COUNT"],
            "filter": {
                "locationFilter": {"customArea": {"polygon": {"coordinates": coordinates}}},
                "typeFilter": {"includedTypes": ["park", "national_park", "playground", "garden"]},
            },
        }, timeout=15)
        if not response.ok:
            error = response.json().get("error", {})
            reasons = ", ".join(detail.get("reason", "") for detail in error.get("details", [])
                                if detail.get("reason"))
            print(f"{suburb}: Google Aggregate HTTP {response.status_code} {reasons}", flush=True)
            if response.status_code in (401, 403, 429):
                raise SystemExit(1)
            continue
        count = response.json().get("count", 0)
        print(f"{suburb}: {count} Google Places inside the ABS boundary", flush=True)


if __name__ == "__main__":
    main()
