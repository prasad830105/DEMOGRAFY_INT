"""Cache-first ingestion for Google Places Aggregate suburb counts."""

import psycopg

from google_boundary_pilot import (
    BoundaryError, BoundaryRejected, coordinates_for_google, count_inside_boundary, load_boundaries,
)
from pipeline import connect


def fresh_results(connection, sal_codes=None):
    if sal_codes is None:
        rows = connection.execute("select sal_code, measured from livability.fresh_boundary_cache")
    else:
        rows = connection.execute("""
            select sal_code, measured from livability.fresh_boundary_cache where sal_code = any(%s)
        """, (sal_codes,))
    return {row["sal_code"]: row["measured"] for row in rows}


def lock_boundary(connection, sal_code, *, wait=True):
    key = f"livability:aggregate:suburb:{sal_code}"
    if wait:
        connection.execute("select pg_advisory_xact_lock(hashtextextended(%s, 0))", (key,))
        return True
    return connection.execute(
        "select pg_try_advisory_xact_lock(hashtextextended(%s, 0)) as locked", (key,),
    ).fetchone()["locked"]


def store_boundary_count(connection, sal_code, count):
    connection.execute("select livability.store_boundary_count(%s, %s)", (sal_code, count))


def ensure_boundary_measurement(database_url, api_key, suburb):
    """Use an unexpired result or fetch and commit one measurement for this suburb."""
    code = suburb.sal_code
    rejected = "Google Places Aggregate cannot measure this ABS boundary."
    try:
        with connect(database_url) as connection:
            fresh = fresh_results(connection, [code])
            if code in fresh:
                return None if fresh[code] else rejected

            lock_boundary(connection, code)
            fresh = fresh_results(connection, [code])
            if code in fresh:
                return None if fresh[code] else rejected
            if not api_key:
                raise BoundaryError("Set GOOGLE_PLACES_AGGREGATE_API_KEY to fetch a new measurement.")

            abs_code = code.removeprefix("SAL")
            geometry = load_boundaries([abs_code])[abs_code]
            try:
                polygon = coordinates_for_google(geometry)
                count = count_inside_boundary(api_key, polygon)
            except (BoundaryRejected, ValueError, KeyError, TypeError):
                store_boundary_count(connection, code, None)
                return rejected
            store_boundary_count(connection, code, count)
            return None
    except psycopg.errors.LockNotAvailable:
        raise BoundaryError("This suburb is already being measured. Try comparing again shortly.") from None
    except psycopg.Error:
        raise BoundaryError("Supabase could not check or save this measurement.") from None
