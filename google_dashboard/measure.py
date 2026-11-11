"""Populate or refresh the fixed outdoor benchmark sample using the suburb cache."""

from argparse import ArgumentParser
from concurrent.futures import ThreadPoolExecutor
from time import monotonic

import streamlit as st

from google_dashboard.outdoor_analysis import BENCHMARK_SUBURBS, benchmark_candidates, is_cbd, load_benchmark
from google_dashboard.pipeline import PARKS_KPI, PipelineError, get_metrics, load_catalog


def main():
    parser = ArgumentParser(description=__doc__)
    parser.add_argument("sal_codes", nargs="*", help="Check additional suburbs without changing the benchmark.")
    args = parser.parse_args()
    database_url = st.secrets["SUPABASE_DB_URL"]
    api_key = st.secrets["GOOGLE_PLACES_API_KEY"]
    catalogue = load_catalog(database_url)
    cohort = benchmark_candidates(catalogue)
    if len(cohort) != sum(map(len, BENCHMARK_SUBURBS.values())):
        raise SystemExit("The suburb catalogue does not contain exactly one match per benchmark suburb.")
    suburbs = cohort
    if args.sal_codes:
        by_code = {suburb.sal_code: suburb for suburb in catalogue}
        suburbs = []
        for code in dict.fromkeys(code.upper() for code in args.sal_codes):
            suburb = by_code.get(code)
            if not suburb:
                parser.error(f"Unknown suburb code {code}.")
            if is_cbd(suburb.suburb_name, suburb.state):
                print(f"Skipped CBD: {suburb.label}")
            else:
                suburbs.append(suburb)

    def measure(suburb):
        try:
            return get_metrics(database_url, api_key, suburb, monotonic() + 15)
        except PipelineError as error:
            return error

    measured = []
    with ThreadPoolExecutor(max_workers=3) as pool:
        for suburb, result in zip(suburbs, pool.map(measure, suburbs), strict=True):
            if isinstance(result, PipelineError):
                print(f"{suburb.label}: {result}", flush=True)
                continue
            count = result["counts"][PARKS_KPI]
            measured.append((count / suburb.area_km2, suburb.label, count, result["source"]))
    for value, label, count, source in sorted(measured, reverse=True):
        print(f"{label}: {count} places, {value:.2f}/km² ({source})", flush=True)

    density, winner, sample_size, _ = load_benchmark(database_url, cohort)
    if density is None:
        raise SystemExit(f"No positive benchmark yet. Fresh measurements: {sample_size}/{len(cohort)}.")
    print(f"100-point benchmark: {winner}, {density:.2f} places/km² ({sample_size} suburbs).")
    for value, label, _, _ in sorted(measured, reverse=True):
        if value > density:
            print(f"Beats the current benchmark: {label}, {value:.2f} places/km².")
    if len(measured) != len(suburbs):
        raise SystemExit("Some measurements failed. Rerun to retry them.")


if __name__ == "__main__":
    main()
