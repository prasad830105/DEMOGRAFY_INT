"""Prepare the attached suburb bounds CSV for Supabase import.

The source provides rectangular extents, not polygon boundaries. Existing ABS
representative points are reused where suburb/state names match uniquely; any
unmatched rows use the bounding-box midpoint as an approximate routing origin.
"""

from __future__ import annotations

import csv
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parent
SOURCE_PATH = ROOT / "suburbs.csv"
CENTRES_PATH = ROOT / "abs_sal_2026_suburbs.csv"
OUTPUT_PATH = ROOT / "suburbs_import.csv"

STATE_CODES = {
    "NSW": ("1", "New South Wales"),
    "VIC": ("2", "Victoria"),
    "QLD": ("3", "Queensland"),
    "SA": ("4", "South Australia"),
    "WA": ("5", "Western Australia"),
    "TAS": ("6", "Tasmania"),
    "NT": ("7", "Northern Territory"),
    "ACT": ("8", "Australian Capital Territory"),
    "OT": ("9", "Other Territories"),
}


def normalise_name(value: str) -> str:
    return re.sub(r"\s+\([^)]*\)$", "", value).strip().casefold()


def main() -> None:
    with SOURCE_PATH.open(encoding="utf-8-sig", newline="") as file:
        source_rows = list(csv.DictReader(file))
    with CENTRES_PATH.open(encoding="utf-8-sig", newline="") as file:
        centre_rows = list(csv.DictReader(file))

    centres_by_code = {row["sal_code"].removeprefix("SAL"): row for row in centre_rows}
    centres_by_name: dict[tuple[str, str], list[dict[str, str]]] = {}
    for row in centre_rows:
        key = (normalise_name(row["sal_name"]), row["state_abbr"])
        centres_by_name.setdefault(key, []).append(row)

    fields = [
        "suburb", "sal_code", "sal_name", "state_code", "state_name", "state_abbr",
        "centre_lat", "centre_lon", "is_active", "legacy_name", "postcode", "area_km2",
        "population", "min_lat", "min_lon", "max_lat", "max_lon",
    ]
    output_rows = []
    reused_centres = 0
    midpoint_centres = 0
    for row in source_rows:
        state = row["state"].strip().upper()
        if state not in STATE_CODES:
            raise ValueError(f"Unknown state abbreviation {state!r} for {row['suburb_name']}.")
        state_code, state_name = STATE_CODES[state]
        code = row["sal_code"].removeprefix("SAL")
        candidate = centres_by_code.get(code)
        if candidate and (
            normalise_name(candidate["sal_name"]) != normalise_name(row["suburb_name"])
            or candidate["state_abbr"] != state
        ):
            candidate = None
        if candidate is None:
            matches = centres_by_name.get((normalise_name(row["suburb_name"]), state), [])
            candidate = matches[0] if len(matches) == 1 else None

        min_lat = float(row["min_lat"])
        min_lon = float(row["min_lon"])
        max_lat = float(row["max_lat"])
        max_lon = float(row["max_lon"])
        if candidate:
            centre_lat = float(candidate["centre_lat"])
            centre_lon = float(candidate["centre_lon"])
            legacy_name = candidate["suburb"]
            reused_centres += 1
        else:
            centre_lat = (min_lat + max_lat) / 2
            centre_lon = (min_lon + max_lon) / 2
            legacy_name = ""
            midpoint_centres += 1

        name = row["suburb_name"].strip()
        output_rows.append({
            "suburb": f"{name}, {state}",
            "sal_code": row["sal_code"].strip(),
            "sal_name": name,
            "state_code": state_code,
            "state_name": state_name,
            "state_abbr": state,
            "centre_lat": f"{centre_lat:.7f}",
            "centre_lon": f"{centre_lon:.7f}",
            "is_active": "true",
            "legacy_name": legacy_name,
            "postcode": row["postcode"].strip(),
            "area_km2": f"{float(row['area_km2']):.4f}",
            "population": row["population"].strip() or "0",
            "min_lat": f"{min_lat:.7f}",
            "min_lon": f"{min_lon:.7f}",
            "max_lat": f"{max_lat:.7f}",
            "max_lon": f"{max_lon:.7f}",
        })

    if len({row["suburb"] for row in output_rows}) != len(output_rows):
        raise ValueError("The generated suburb labels are not unique.")
    if len({row["sal_code"] for row in output_rows}) != len(output_rows):
        raise ValueError("The source SAL codes are not unique.")

    with OUTPUT_PATH.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fields)
        writer.writeheader()
        writer.writerows(output_rows)

    print(f"Wrote {len(output_rows):,} suburb rows to {OUTPUT_PATH.name}.")
    print(f"Reused ABS representative point: {reused_centres:,}; used bounds midpoint: {midpoint_centres:,}.")


if __name__ == "__main__":
    main()
