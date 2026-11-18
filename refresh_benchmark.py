"""Populate or refresh the fixed outdoor benchmark sample using the suburb cache."""

from argparse import ArgumentParser
from concurrent.futures import ThreadPoolExecutor
from time import monotonic

import streamlit as st

from outdoor_analysis import BENCHMARK_SUBURBS, benchmark_candidates, is_cbd, load_benchmark
from pipeline import PARKS_KPI, SEARCH_TIMEOUT_SECONDS, PipelineError, get_metrics, load_catalog


def main():
    parser = ArgumentParser(description=__doc__)
    parser.add_argument("sal_codes", nargs="*", help="Check additional suburbs without changing the reference sample.")
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
            if suburb is None:
                parser.error(f"Unknown suburb code {code}.")
            if is_cbd(suburb.suburb_name, suburb.state):
                print(f"Skipped CBD: {suburb.label}")
            else:
                suburbs.append(suburb)

    def measure(suburb):
        try:
            return get_metrics(database_url, api_key, suburb, monotonic() + SEARCH_TIMEOUT_SECONDS)
        except PipelineError as error:
            return error

    measurements = []
    with ThreadPoolExecutor(max_workers=3) as pool:
        for suburb, result in zip(suburbs, pool.map(measure, suburbs), strict=True):
            if isinstance(result, PipelineError):
                print(f"{suburb.label}: {result}", flush=True)
                continue
            count = result["counts"][PARKS_KPI]
            suburb_density = count / suburb.area_km2
            measurements.append((suburb_density, suburb.label))
            cap_note = ", a smallest search area reached the result limit" if result["search_capped"] else ""
            print(f"{suburb.label}: {count} places, {suburb_density:.2f}/km² "
                  f"({result['source']}{cap_note})", flush=True)

    density, winner, sample_size, _ = load_benchmark(database_url, cohort)
    if density is None:
        raise SystemExit(f"No positive benchmark yet. Fresh measurements: {sample_size}/{len(cohort)}.")
    print(f"100-point benchmark: {winner}, {density:.2f} places/km² ({sample_size} suburbs).")
    if args.sal_codes:
        for suburb_density, label in sorted(measurements, reverse=True):
            if suburb_density > density:
                print(f"Beats the current benchmark: {label}, {suburb_density:.2f} places/km².")
    if len(measurements) != len(suburbs):
        raise SystemExit("Some measurements failed. Rerun to retry them.")


if __name__ == "__main__":
    main()
