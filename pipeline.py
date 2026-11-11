"""On-demand Google Places ingestion and PostgreSQL cache."""

from dataclasses import dataclass
from time import monotonic

import psycopg
import requests
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

PARKS_KPI = "Parks and outdoor places"
SEARCH_VERSION = 2
GOOGLE_URL = "https://places.googleapis.com/v1/places:searchText"


class PipelineError(Exception):
    """An error safe to show in the dashboard."""


@dataclass(frozen=True)
class Suburb:
    sal_code: str
    suburb_name: str
    state: str
    postcode: str | None
    area_km2: float
    population: int | None
    min_lat: float
    min_lon: float
    max_lat: float
    max_lon: float

    @property
    def label(self):
        return " · ".join(filter(None, (self.suburb_name, self.state, self.postcode)))

    @property
    def rectangle(self):
        return {
            "low": {"latitude": self.min_lat, "longitude": self.min_lon},
            "high": {"latitude": self.max_lat, "longitude": self.max_lon},
        }


def connect(database_url):
    return psycopg.connect(
        database_url,
        connect_timeout=4,
        options="-c statement_timeout=3500 -c lock_timeout=2500",
        row_factory=dict_row,
    )


def load_catalog(database_url):
    with connect(database_url) as connection:
        rows = connection.execute("""
            select sal_code::text, suburb_name, state, postcode::text,
                   area_km2::float8, population::bigint,
                   min_lat::float8, min_lon::float8, max_lat::float8, max_lon::float8
            from livability.suburb_catalog
            where area_km2 > 0
              and min_lat >= -90 and max_lat <= 90 and min_lat < max_lat
              and min_lon >= -180 and max_lon <= 180 and min_lon < max_lon
            order by suburb_name, state, postcode, sal_code
        """).fetchall()
    return [Suburb(**row) for row in rows]


def search_category(suburb, query, api_key, deadline):
    body = {
        "textQuery": query,
        "regionCode": "AU",
        "languageCode": "en-AU",
        "pageSize": 20,
        "locationRestriction": {"rectangle": suburb.rectangle},
    }
    headers = {
        "X-Goog-Api-Key": api_key,
        "X-Goog-FieldMask": "places.id,nextPageToken",
    }
    ids = set()
    with requests.Session() as session:
        for _ in range(3):
            remaining = deadline - monotonic()
            if remaining <= 0:
                raise PipelineError("The Places search timed out. Try comparing again.")
            try:
                response = session.post(
                    GOOGLE_URL, json=body, headers=headers,
                    timeout=(min(2, remaining / 2), min(5, remaining / 2)),
                )
                response.raise_for_status()
                page = response.json()
                ids.update(place["id"] for place in page.get("places", []))
            except requests.HTTPError as error:
                code = error.response.status_code
                if code in (401, 403):
                    raise PipelineError("Google denied the Places request. Check the API key and Places API (New) access.") from None
                if code == 429:
                    raise PipelineError("Google Places reached its request or quota limit. Try again later.") from None
                raise PipelineError(f"Google Places returned HTTP {code}.") from None
            except (requests.RequestException, ValueError, KeyError):
                raise PipelineError("Google Places could not return a complete response. Try again.") from None
            token = page.get("nextPageToken")
            if not token:
                break
            body["pageToken"] = token
    return sorted(ids)


def get_metrics(database_url, api_key, suburb, deadline):
    """Serialize refreshes for one suburb and publish only complete snapshots."""
    key = (suburb.sal_code, SEARCH_VERSION)
    bounds = Jsonb(suburb.rectangle)
    select_metrics = """
        select refreshed_at, counts
        from livability.amenity_metrics
        where sal_code = %s and search_version = %s and bounds = %s
          and refreshed_at + interval '1 month' > statement_timestamp()
    """
    try:
        with connect(database_url) as connection:
            metrics = connection.execute(select_metrics, (*key, bounds)).fetchone()
            if metrics:
                return {**metrics, "source": "Supabase cache"}

            connection.execute(
                "select pg_advisory_xact_lock(hashtextextended(%s, 0))",
                (f"livability:{suburb.sal_code}:{SEARCH_VERSION}",),
            )
            metrics = connection.execute(select_metrics, (*key, bounds)).fetchone()
            if metrics:
                return {**metrics, "source": "Supabase cache"}

            snapshot = {
                PARKS_KPI: search_category(
                    suburb, "public parks, gardens and outdoor recreation areas", api_key, deadline
                )
            }

            connection.execute("""
                insert into livability.place_snapshots (sal_code, search_version, bounds, place_ids)
                values (%s, %s, %s, %s)
                on conflict (sal_code, search_version) do update
                    set bounds = excluded.bounds, place_ids = excluded.place_ids,
                        refreshed_at = statement_timestamp()
            """, (*key, bounds, Jsonb(snapshot)))
            metrics = connection.execute(select_metrics, (*key, bounds)).fetchone()
            return {**metrics, "source": "Google Maps"}
    except psycopg.errors.LockNotAvailable:
        raise PipelineError("This suburb is already being refreshed. Try comparing again shortly.") from None
    except psycopg.errors.UndefinedTable:
        raise PipelineError("The Supabase migration is missing. Apply supabase.sql and try again.") from None
    except psycopg.Error:
        raise PipelineError("Supabase could not complete the comparison. Check the connection and database permissions.") from None
