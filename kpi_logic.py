"""Pure KPI definitions and calculations shared by the app and local checks."""

from __future__ import annotations

from typing import Optional


CATEGORY = "Parks"
DISPLAY_NAME = "Parks & Outdoor Places"
OSM_SOURCE = "osm_overpass_bbox_green_recreation"
OSM_LEISURE_TAGS = ("park", "garden", "nature_reserve", "playground")


def density(place_count: int | float | None, area_km2: int | float | None) -> Optional[float]:
    """Return mapped features per km², or None when inputs are unusable."""
    if place_count is None or area_km2 is None:
        return None
    if place_count < 0 or area_km2 <= 0:
        return None
    return float(place_count) / float(area_km2)


def score(density_value: float | None, benchmark_density: float | None) -> Optional[float]:
    """Scale density against the comparison pair's higher density (0–100)."""
    if density_value is None or benchmark_density is None:
        return None
    if density_value <= 0 or benchmark_density <= 0:
        return 0.0
    return min(100.0, 100.0 * density_value / benchmark_density)


def pair_scores(density_a: float | None, density_b: float | None) -> tuple[Optional[float], Optional[float]]:
    """Return scores for a pair, with the denser suburb benchmarked at 100."""
    if density_a is None or density_b is None:
        return score(density_a, None), score(density_b, None)
    benchmark = max(density_a, density_b)
    return score(density_a, benchmark), score(density_b, benchmark)
