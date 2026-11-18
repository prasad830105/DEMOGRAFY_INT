"""Test three ABS suburb polygons with Google Places Aggregate."""

import re
from itertools import groupby

import requests
import streamlit as st

ABS_URL = "https://geo.abs.gov.au/arcgis/rest/services/ASGS2021/SAL/MapServer/0/query"
GOOGLE_URL = "https://areainsights.googleapis.com/v1:computeInsights"
PILOT = {"12969": "Newtown, NSW", "20495": "Carlton, VIC", "32587": "South Brisbane, QLD"}
MAX_POLYGON_VERTICES = 7000


def coordinates_for_google(geometry):
    rings = geometry["coordinates"]
    if geometry["type"] == "MultiPolygon" and len(rings) == 1:
        rings = rings[0]
    elif geometry["type"] != "Polygon":
        raise ValueError("Google custom areas require a single polygon.")
    if len(rings) != 1:
        raise ValueError("Google custom areas require a polygon without holes.")
    ring = [point for point, _ in groupby(map(tuple, rings[0]))]
    if len(ring) < 4 or ring[0] != ring[-1]:
        raise ValueError("The ABS polygon must be a closed ring.")
    if len(ring) > MAX_POLYGON_VERTICES:
        raise ValueError("The ABS polygon exceeds Google's vertex limit.")
    if len(set(ring[:-1])) != len(ring) - 1:
        raise ValueError("The ABS polygon repeats a non-adjacent vertex.")
    origin_x, origin_y = ring[0]
    offsets = [(x - origin_x, y - origin_y) for x, y in ring]
    signed_area = sum(x1*y2 - x2*y1 for (x1,y1), (x2,y2) in zip(offsets, offsets[1:]))
    if signed_area == 0:
        raise ValueError("The ABS polygon has no area.")
    if signed_area < 0:
        ring = list(reversed(ring))
    return [{"latitude": lat, "longitude": lon} for lon, lat in ring]


class BoundaryError(Exception):
    """A boundary comparison error safe to display."""


class BoundaryRejected(BoundaryError):
    """Google explicitly rejected the polygon or its area."""


def load_boundaries(codes):
    if not codes or any(not re.fullmatch(r"[0-9]{5}", code) for code in codes):
        raise BoundaryError("The selected suburbs must have valid ABS SAL codes.")
    ids = ", ".join(f"'{code}'" for code in codes)
    try:
        response = requests.get(ABS_URL, params={
            "where": f"SAL_CODE_2021 IN ({ids})",
            "outFields": "SAL_CODE_2021",
            "returnGeometry": "true",
            "outSR": "4326",
            "f": "geojson",
        }, timeout=15)
        response.raise_for_status()
        features = {str(feature["properties"]["sal_code_2021"]): feature["geometry"]
                    for feature in response.json()["features"]}
    except (requests.RequestException, ValueError, KeyError, TypeError):
        raise BoundaryError("Could not load the suburb boundaries from ABS.") from None
    if not set(codes).issubset(features):
        raise BoundaryError("ABS did not return a boundary for every selected suburb.")
    return features


def count_inside_boundary(api_key, coordinates, session=requests):
    try:
        response = session.post(GOOGLE_URL, headers={"X-Goog-Api-Key": api_key}, json={
            "insights": ["INSIGHT_COUNT"],
            "filter": {
                "locationFilter": {"customArea": {"polygon": {"coordinates": coordinates}}},
                "typeFilter": {"includedTypes": ["park", "national_park", "playground", "garden"]},
            },
        }, timeout=15)
    except requests.RequestException:
        raise BoundaryError("Could not connect to Google Places Aggregate.") from None
    try:
        payload = response.json()
    except ValueError:
        raise BoundaryError(f"Google Places Aggregate returned HTTP {response.status_code}.") from None
    if not response.ok:
        error = payload.get("error", {})
        reasons = {detail.get("reason") for detail in error.get("details", [])}
        if "API_KEY_SERVICE_BLOCKED" in reasons:
            raise BoundaryError("The Google API key blocks Places Aggregate API. Allow it in the key’s API restrictions, or configure GOOGLE_PLACES_AGGREGATE_API_KEY.")
        if "SERVICE_DISABLED" in reasons:
            raise BoundaryError("Enable Places Aggregate API on the project that owns the configured key.")
        if response.status_code == 429:
            raise BoundaryError("Google Places Aggregate reached its request or quota limit.")
        message = error.get("message", "")
        if response.status_code == 400 and any(term in message.lower() for term in ("polygon", "location filter", "square meters")):
            raise BoundaryRejected("Google Places Aggregate rejected this ABS polygon.")
        raise BoundaryError(f"Google Places Aggregate returned HTTP {response.status_code}.")
    try:
        count = int(payload.get("count", 0))
    except (ValueError, TypeError, AttributeError):
        raise BoundaryError("Google Places Aggregate returned an invalid count.") from None
    if count < 0:
        raise BoundaryError("Google Places Aggregate returned an invalid count.")
    return count


def compare_exact_boundaries(api_key, suburb_labels):
    features = load_boundaries(list(suburb_labels))
    polygons = {}
    for code, label in suburb_labels.items():
        try:
            polygons[code] = coordinates_for_google(features[code])
        except (ValueError, KeyError, TypeError) as error:
            raise BoundaryError(f"{label}: {error}") from None
    return {code: count_inside_boundary(api_key, polygon) for code, polygon in polygons.items()}


def main():
    api_key = st.secrets.get("GOOGLE_PLACES_AGGREGATE_API_KEY") or st.secrets["GOOGLE_PLACES_API_KEY"]
    try:
        counts = compare_exact_boundaries(api_key, PILOT)
    except BoundaryError as error:
        raise SystemExit(str(error)) from None
    for code, label in PILOT.items():
        print(f"{label}: {counts[code]} Google Places inside the ABS boundary")


if __name__ == "__main__":
    main()
