"""Preflight, fetch and publish the parks KPI for ABS suburb polygons."""

import argparse
import os
import tomllib
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack
from itertools import batched
from pathlib import Path
from time import monotonic, sleep

import psycopg
import requests
import shapefile

from google_boundary_pilot import (
    MAX_POLYGON_VERTICES, BoundaryError, BoundaryRejected, coordinates_for_google, count_inside_boundary,
)
from boundary_store import fresh_results, lock_boundary, store_boundary_count
from pipeline import connect

WORKERS = 8


def inspect_boundaries(reader, catalogue):
    by_abs_code = {code.removeprefix("SAL"): code for code in catalogue}
    eligible = {}
    excluded = Counter({"No ABS polygon": len(catalogue)})
    for record in reader.iterShapeRecords(fields=["SAL_CODE21"]):
        code = by_abs_code.get(record.record["SAL_CODE21"])
        if code is None or record.shape.shapeType == shapefile.NULL:
            continue
        excluded["No ABS polygon"] -= 1
        area = catalogue[code]["area_km2"]
        if area is None or not 0.00155686 <= area <= 2_000_000:
            excluded["Outside Google area limits"] += 1
        elif len(record.shape.parts) != 1:
            excluded["Multiple rings"] += 1
        elif len(record.shape.points) > MAX_POLYGON_VERTICES:
            excluded["Over 7,000 vertices"] += 1
        else:
            try:
                coordinates_for_google({"type": "Polygon", "coordinates": [record.shape.points]})
            except ValueError:
                excluded["Invalid ring"] += 1
            else:
                eligible[code] = record.record.oid
    return eligible, +excluded


def fetch_count(session, api_key, coordinates):
    try:
        return count_inside_boundary(api_key, coordinates, session)
    except BoundaryRejected:
        return None


def fetch_missing(connection, reader, eligible, pending, api_key):
    with ExitStack() as stack:
        sessions = [stack.enter_context(requests.Session()) for _ in range(WORKERS)]
        pool = stack.enter_context(ThreadPoolExecutor(max_workers=WORKERS))
        fetched = 0
        for codes in batched(pending, WORKERS):
            started = monotonic()
            errors = []
            with connection.transaction():
                locked = [code for code in codes if lock_boundary(connection, code, wait=False)]
                fresh = fresh_results(connection, locked)
                missing = [code for code in locked if code not in fresh]
                polygons = [
                    coordinates_for_google({"type": "Polygon", "coordinates": [reader.shape(eligible[code]).points]})
                    for code in missing
                ]
                futures = [pool.submit(fetch_count, session, api_key, polygon)
                           for session, polygon in zip(sessions[:len(missing)], polygons, strict=True)]
                for code, future in zip(missing, futures, strict=True):
                    try:
                        count = future.result()
                    except BoundaryError as error:
                        errors.append(f"{code}: {error}")
                    else:
                        store_boundary_count(connection, code, count)
                        fetched += 1
            if errors:
                raise BoundaryError(errors[0])
            if fetched and fetched % 200 < len(missing):
                print(f"Saved {fetched:,} request results so far.", flush=True)
            sleep(max(0, 1 - (monotonic() - started)))
        print(f"Saved {fetched:,} request results.", flush=True)


def report_benchmark(connection):
    benchmark = connection.execute("""
        select benchmark_name, measured_suburbs, catalogue_suburbs from livability.current_boundary_benchmark
    """).fetchone()
    if benchmark is None:
        print("The benchmark needs a fresh measurement with a positive parks density outside CBDs.")
        return
    print(f"100-point benchmark: {benchmark['benchmark_name']}.")
    print(f"Coverage: {benchmark['measured_suburbs']:,}/{benchmark['catalogue_suburbs']:,} suburbs.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("boundaries", type=Path, help="Official ABS SAL 2021 GDA2020 shapefile ZIP")
    parser.add_argument("--fetch", type=int, metavar="MAX_REQUESTS", help="Maximum Google requests for this run")
    args = parser.parse_args()
    if args.fetch is not None and args.fetch < 0:
        parser.error("--fetch must be nonnegative")

    secrets_file = Path(__file__).with_name(".streamlit") / "secrets.toml"
    secrets = tomllib.loads(secrets_file.read_text(encoding="utf-8")) if secrets_file.exists() else {}
    database_url = os.getenv("SUPABASE_ADMIN_DB_URL") or os.getenv("SUPABASE_DB_URL") or secrets.get("SUPABASE_DB_URL")
    if not database_url:
        parser.error("Configure SUPABASE_DB_URL or SUPABASE_ADMIN_DB_URL.")
    with connect(database_url) as connection, shapefile.Reader(str(args.boundaries)) as reader:
        connection.autocommit = True
        catalogue = {row["sal_code"]: row for row in connection.execute("""
            select sal_code, suburb_name, state, area_km2 from livability.suburb_catalog order by sal_code
        """)}
        eligible, excluded = inspect_boundaries(reader, catalogue)
        print(f"Eligible for one exact polygon request: {len(eligible):,}/{len(catalogue):,} suburbs.", flush=True)
        for reason, count in excluded.most_common():
            print(f"  {reason}: {count:,}", flush=True)
        if args.fetch is None:
            return
        if not eligible:
            raise BoundaryError("No usable polygons found in the supplied boundary file.")
        api_key = os.getenv("GOOGLE_PLACES_AGGREGATE_API_KEY") or secrets.get("GOOGLE_PLACES_AGGREGATE_API_KEY")
        if args.fetch and not api_key:
            parser.error("Configure GOOGLE_PLACES_AGGREGATE_API_KEY.")
        if not connection.execute("""
            select pg_try_advisory_lock(hashtextextended('livability:aggregate:batch', 0)) as locked
        """).fetchone()["locked"]:
            raise BoundaryError("Another national batch is already running.")
        if not connection.execute("""
            select 1 from cron.job where jobname = 'livability-purge-aggregate-counts' and active
        """).fetchone():
            raise BoundaryError("The Supabase cache purge job must be active before fetching.")
        fresh = fresh_results(connection)
        pending = [code for code in eligible if code not in fresh]
        print(f"Cache hits: {len(eligible) - len(pending):,}. Requesting up to {min(len(pending), args.fetch):,}.", flush=True)
        if pending and args.fetch:
            fetch_missing(connection, reader, eligible, pending[:args.fetch], api_key)
        report_benchmark(connection)


if __name__ == "__main__":
    try:
        main()
    except BoundaryError as error:
        raise SystemExit(str(error)) from None
    except psycopg.Error:
        raise SystemExit("Supabase could not complete the batch. Check the admin connection and boundary_cache.sql migration.") from None
