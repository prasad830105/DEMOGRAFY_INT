"""Prepare the ABS ASGS 2026 SAL shapefile for import into Supabase."""

import csv
from pathlib import Path

import shapefile
from pyproj import Transformer
from shapely.geometry import shape as make_geometry


SOURCE = Path("sal_2026_boundary_tmp/SAL_2026_AUST_GDA2020.shp")
OUTPUT = Path("abs_sal_2026_suburbs.csv")
EXISTING_UPDATES = Path("supabase_suburbs_existing_rows.sql")
STATE_ABBR = {
    "1": "NSW",
    "2": "VIC",
    "3": "QLD",
    "4": "SA",
    "5": "WA",
    "6": "TAS",
    "7": "NT",
    "8": "ACT",
    "9": "OT",
}
LEGACY_KEYS = {
    ("Chatswood", "NSW"): "Chatswood, NSW",
    ("Newtown (NSW)", "NSW"): "Newtown, NSW",
    ("Parramatta", "NSW"): "Parramatta, NSW",
}
COLUMNS = [
    "suburb",
    "sal_code",
    "sal_name",
    "state_code",
    "state_name",
    "state_abbr",
    "centre_lat",
    "centre_lon",
    "is_active",
    "legacy_name",
]


def main() -> None:
    transformer = Transformer.from_crs("EPSG:7844", "EPSG:4326", always_xy=True)
    reader = shapefile.Reader(str(SOURCE))
    labels: set[str] = set()
    existing_updates: list[dict[str, str]] = []
    count = 0
    with OUTPUT.open("w", newline="", encoding="utf-8-sig") as output:
        writer = csv.DictWriter(output, fieldnames=COLUMNS)
        writer.writeheader()
        for item in reader.iterShapeRecords():
            properties = item.record.as_dict()
            if item.shape.shapeType == 0:
                continue  # exclude non-spatial statistical placeholders
            sal_name = properties["SAL_NAME26"]
            state_code = str(properties["STE_CODE26"])
            state_name = properties["STE_NAME26"]
            state_abbr = STATE_ABBR[state_code]
            legacy_name = LEGACY_KEYS.get((sal_name, state_abbr))
            suburb = legacy_name or sal_name
            if suburb in labels:
                raise ValueError(f"Duplicate suburb label: {suburb}")
            labels.add(suburb)

            point = make_geometry(item.shape.__geo_interface__).representative_point()
            longitude, latitude = transformer.transform(point.x, point.y)
            row = {
                    "suburb": suburb,
                    "sal_code": properties["SAL_CODE26"],
                    "sal_name": sal_name,
                    "state_code": state_code,
                    "state_name": state_name,
                    "state_abbr": state_abbr,
                    "centre_lat": f"{latitude:.7f}",
                    "centre_lon": f"{longitude:.7f}",
                    "is_active": "true",
                    "legacy_name": legacy_name or "",
                }
            if legacy_name:
                existing_updates.append(row)
            else:
                writer.writerow(row)
                count += 1
    with EXISTING_UPDATES.open("w", encoding="utf-8") as sql:
        sql.write("-- Run after supabase_suburbs.sql to attach ABS identifiers and centres to the 3 existing prototype rows.\n")
        for row in existing_updates:
            values = ",\n    ".join(
                [
                    f"sal_code = '{row['sal_code']}'",
                    f"sal_name = '{row['sal_name'].replace(chr(39), chr(39) * 2)}'",
                    f"state_code = '{row['state_code']}'",
                    f"state_name = '{row['state_name']}'",
                    f"state_abbr = '{row['state_abbr']}'",
                    f"centre_lat = {row['centre_lat']}",
                    f"centre_lon = {row['centre_lon']}",
                    "is_active = true",
                    f"legacy_name = '{row['legacy_name']}'",
                ]
            )
            sql.write(f"\nupdate public.suburbs set\n    {values}\nwhere suburb = '{row['suburb']}';\n")
    print(
        f"Prepared {count} new spatial suburbs/localities "
        f"({OUTPUT.stat().st_size:,} bytes), plus {len(existing_updates)} existing-row updates."
    )


if __name__ == "__main__":
    main()
