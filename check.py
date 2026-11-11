"""Project-specific, offline checks for the Demografy OSM parks app.

Run one stage with ``python check.py A`` through ``python check.py E`` or
run all stages with ``python check.py ALL``. Network and database behaviors
are exercised with local fakes; no real API keys or Supabase writes are used.

Stages map to the mentor checker while reflecting this app's implementation:
A KPI and scores; B Supabase and cache; C OSM queries; D comparison and batch
loading; E suburb bounding-box filtering and its documented limitation.
"""

from __future__ import annotations

import ast
import csv
import operator
import sys
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Callable

import pandas as pd
import requests

from kpi_logic import (
    CATEGORY,
    DISPLAY_NAME,
    OSM_LEISURE_TAGS,
    OSM_SOURCE,
    density,
    pair_scores,
    score,
)


ROOT = Path(__file__).resolve().parent
APP_PATH = ROOT / "app.py"
CATALOGUE_PATH = ROOT / "suburbs_import.csv"
STARTER_LIST_PATH = ROOT / "popular_suburbs.csv"
failures = 0
checks_run = 0


def check(description: str, test: Callable[[], bool]) -> None:
    """Print a stable PASS/FAIL line while allowing a stage to finish."""
    global failures, checks_run
    checks_run += 1
    try:
        ok = bool(test())
        detail = "" if ok else " (wrong result)"
    except Exception as exc:  # keep a useful diagnostic for junior learners
        ok, detail = False, f" ({type(exc).__name__}: {exc})"
    print(f"{'PASS' if ok else 'FAIL'}  {description}{detail}")
    failures += int(not ok)


def source_tree() -> ast.Module:
    return ast.parse(APP_PATH.read_text(encoding="utf-8"))


def function_node(name: str) -> ast.FunctionDef:
    for node in source_tree().body:
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise LookupError(f"Function {name} was not found in app.py")


def app_function(name: str, **overrides):
    """Load one real app function without executing Streamlit's page script."""
    node = function_node(name)
    node.decorator_list = []  # remove only Streamlit's cache wrapper
    module = ast.Module(body=[node], type_ignores=[])
    namespace = {
        "datetime": datetime,
        "timezone": timezone,
        "requests": requests,
        "pd": pd,
        "CATEGORY": CATEGORY,
        "OSM_SOURCE": OSM_SOURCE,
        "OSM_LEISURE_TAGS": OSM_LEISURE_TAGS,
        **overrides,
    }
    exec(compile(ast.fix_missing_locations(module), str(APP_PATH), "exec"), namespace)
    return namespace[name], namespace


def catalogue_rows() -> list[dict[str, str]]:
    with CATALOGUE_PATH.open(encoding="utf-8-sig", newline="") as csv_file:
        return list(csv.DictReader(csv_file))


def numeric_expression(node: ast.AST):
    """Evaluate only basic numeric literals and arithmetic in cache decorators."""
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return node.value
    if isinstance(node, ast.BinOp):
        operations = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
                      ast.Div: operator.truediv, ast.FloorDiv: operator.floordiv}
        operation = operations.get(type(node.op))
        if operation:
            return operation(numeric_expression(node.left), numeric_expression(node.right))
    raise ValueError("unsupported cache-TTL expression")


def named_suburb(label: str) -> dict[str, str]:
    for row in catalogue_rows():
        if row.get("suburb", "").casefold() == label.casefold():
            return row
    raise LookupError(f"{label} was not found in suburbs_import.csv")


def stage_a() -> None:
    check("KPI category is Parks and display name is buyer-facing", lambda:
          CATEGORY == "Parks" and DISPLAY_NAME == "Parks & Outdoor Places")
    check("OSM KPI contains the four agreed leisure tags", lambda:
          set(OSM_LEISURE_TAGS) == {"park", "garden", "nature_reserve", "playground"})
    check("density(42, 0.8647 km²) displays as 48.6 features/km²", lambda:
          round(density(42, 0.8647), 1) == 48.6)
    check("zero or invalid area does not produce a density", lambda:
          density(5, 0) is None and density(5, -1) is None)
    check("pair score: 40 vs 80 is 50; higher density is capped at 100", lambda:
          score(40, 80) == 50 and score(120, 80) == 100 and score(None, 80) is None)
    check("both zero-density suburbs score zero", lambda:
          pair_scores(0, 0) == (0.0, 0.0))
    check("ABS suburb catalogue has real suburb rows with positive area and bounds", lambda:
          len(catalogue_rows()) >= 2 and all(
              float(row["area_km2"]) > 0
              and all(row.get(key) for key in ("min_lat", "min_lon", "max_lat", "max_lon"))
              for row in catalogue_rows()[:100]
          ))

    # A real comparison observed in the running app with counts loaded from Supabase.
    chat = named_suburb("Chatswood, NSW")
    newtown = named_suburb("Newtown, NSW")
    chat_density = density(95, float(chat["area_km2"]))
    newtown_density = density(86, float(newtown["area_km2"]))
    chat_score, newtown_score = pair_scores(chat_density, newtown_density)
    check("recorded Supabase comparison: Chatswood 95 vs Newtown 86 gives 35 vs 100", lambda:
          (round(chat_score), round(newtown_score)) == (35, 100))


def stage_b() -> None:
    app_source = APP_PATH.read_text(encoding="utf-8")
    cache_ttls = {}
    for node in source_tree().body:
        if isinstance(node, ast.FunctionDef):
            for decorator in node.decorator_list:
                if (isinstance(decorator, ast.Call)
                        and isinstance(decorator.func, ast.Attribute)
                        and decorator.func.attr == "cache_data"):
                    for keyword in decorator.keywords:
                        if keyword.arg == "ttl":
                            cache_ttls[node.name] = numeric_expression(keyword.value)

    check("search and saved-count functions have bounded Streamlit cache TTLs", lambda:
          cache_ttls.get("search_suburbs") == 600
          and cache_ttls.get("load_saved_counts") == 900
          and cache_ttls.get("load_osm_counts") == 86400)

    saved_requests = []
    def fake_supabase_request(method, path, *, params=None, json=None, prefer=None):
        saved_requests.append((method, path, params or {}, json, prefer))
        if method == "GET" and path == "suburbs":
            return [{"suburb": "Newtown, NSW", "sal_code": "SAL123", "state_abbr": "NSW"}]
        if method == "GET" and path == "amenity_counts":
            return [{"suburb": params["suburb"][3:], "place_count": 86}]
        return []

    search, _ = app_function(
        "search_suburbs", supabase_config=lambda: ("https://sample.supabase.co", "test-key"),
        supabase_request=fake_supabase_request, local_suburb_matches=lambda query: [],
    )
    results, error = search("Newtown, NSW")
    search_params = next(item[2] for item in saved_requests if item[1] == "suburbs")
    check("suburb search queries active Supabase rows with a bounded 25-row result", lambda:
          error is None and results[0]["suburb"] == "Newtown, NSW"
          and search_params.get("is_active") == "eq.true"
          and search_params.get("limit") == "25"
          and search_params.get("suburb") == "ilike.*Newtown, NSW*")

    saved_requests.clear()
    load_saved, _ = app_function("load_saved_counts", supabase_request=fake_supabase_request)
    counts, error = load_saved((("Newtown, NSW", "Newtown"),), source=OSM_SOURCE)
    count_params = [item[2] for item in saved_requests if item[1] == "amenity_counts"]
    check("saved KPI lookup filters selected suburb, Parks category and current OSM source", lambda:
          error is None and counts == {"Newtown, NSW": 86}
          and count_params[0].get("category") == "eq.Parks"
          and count_params[0].get("source") == f"eq.{OSM_SOURCE}"
          and count_params[0].get("suburb") == "eq.Newtown, NSW")

    saved_requests.clear()
    save, _ = app_function("save_osm_counts", supabase_request=fake_supabase_request)
    save({"Newtown, NSW": 86})
    method, path, params, payload, prefer = saved_requests[-1]
    check("successful OSM counts upsert place_count, category, source and timestamp", lambda:
          method == "POST" and path == "amenity_counts"
          and params.get("on_conflict") == "suburb,category"
          and prefer == "resolution=merge-duplicates,return=minimal"
          and payload[0].get("place_count") == 86
          and payload[0].get("category") == CATEGORY
          and payload[0].get("source") == OSM_SOURCE
          and bool(payload[0].get("updated_at")))

    class FakeResponse:
        content = b"[]"
        def raise_for_status(self):
            pass
        def json(self):
            return []

    http_calls = []
    fake_requests = SimpleNamespace(request=lambda *args, **kwargs: (http_calls.append((args, kwargs)) or FakeResponse()))
    request, _ = app_function(
        "supabase_request", supabase_config=lambda: ("https://sample.supabase.co", "local-test-key"),
        requests=fake_requests,
    )
    request("GET", "suburbs", params={"limit": "25"})
    call_args, call_kwargs = http_calls[0]
    check("Supabase REST request uses project REST URL, anon headers and status handling", lambda:
          call_args[:2] == ("GET", "https://sample.supabase.co/rest/v1/suburbs")
          and call_kwargs["headers"].get("apikey") == "local-test-key"
          and call_kwargs["headers"].get("Authorization") == "Bearer local-test-key"
          and call_kwargs["timeout"] == 20)


class FakeOverpassResponse:
    def __init__(self, elements):
        self._elements = elements
    def raise_for_status(self):
        pass
    def json(self):
        return {"elements": self._elements}


def stage_c() -> None:
    elements = [
        {"type": "node", "id": 1, "lat": 0.5, "lon": 0.5, "tags": {"leisure": "park"}},
        {"type": "node", "id": 1, "lat": 0.5, "lon": 0.5, "tags": {"leisure": "park"}},
        {"type": "way", "id": 1, "center": {"lat": 0.6, "lon": 0.6}, "tags": {"leisure": "playground"}},
        {"type": "relation", "id": 1, "center": {"lat": 10.5, "lon": 10.5}, "tags": {"leisure": "nature_reserve"}},
        {"type": "node", "id": 8, "lat": 0.5, "lon": 0.5, "tags": {"leisure": "cafe"}},
        {"type": "node", "id": 9, "lat": 2, "lon": 2, "tags": {"leisure": "park"}},
        {"type": "way", "id": 4, "tags": {"leisure": "garden"}},
    ]
    queries = []
    class FakeSession:
        def post(self, endpoint, *, data, headers, timeout):
            queries.append(data["data"])
            return FakeOverpassResponse(elements)

    fetch, _ = app_function(
        "fetch_osm_batch", session=FakeSession(), OVERPASS_ENDPOINTS=("https://overpass.example/api",),
    )
    counts = fetch((
        ("Alpha, NSW", 0, 0, 1, 1),
        ("Beta, NSW", 10, 10, 11, 11),
    ))
    check("Overpass batch requests the four agreed OSM leisure tags and returns a count per suburb", lambda:
          len(queries) == 1
          and '"leisure"~"^(park|garden|nature_reserve|playground)$"' in queries[0]
          and counts == {"Alpha, NSW": 2, "Beta, NSW": 1})
    check("Overpass query is one batched request with center output for ways and relations", lambda:
          queries[0].count("nwr(") == 2 and "out center;" in queries[0]
          and "[out:json][timeout:60]" in queries[0])
    check("same OSM element ID is deduplicated by type and ID, while a different type remains distinct", lambda:
          counts["Alpha, NSW"] == 2)


def stage_d() -> None:
    label, _ = app_function("suburb_label")
    check("comparison labels preserve state in search results", lambda:
          label({"suburb": "Newtown, NSW", "state_abbr": "NSW"}) == "Newtown, NSW"
          and label({"suburb": "Bondi", "state_abbr": "NSW"}) == "Bondi · NSW")

    rows = [{
        "suburb": f"Test Area {i}, NSW", "state_abbr": "NSW", "legacy_name": "",
        "min_lat": str(i), "min_lon": "0", "max_lat": str(i + 1), "max_lon": "1",
        "area_km2": "1.0",
    } for i in range(8)]
    batch_calls, saved_payloads = [], []
    def fake_batch(bounds):
        batch_calls.append(tuple(bounds))
        return {bound[0]: 10 + index for index, bound in enumerate(bounds)}
    class FakeProgress:
        def progress(self, *args, **kwargs):
            pass
    loader, _ = app_function(
        "load_suburb_kpi_data", load_bulk_saved_counts=lambda: {
            "Test Area 0, NSW": 7, "Test Area 1, NSW": 8,
        },
        fetch_osm_batch=fake_batch,
        save_osm_counts=lambda counts: saved_payloads.append(dict(counts)),
    )
    result, errors, synced = loader(rows, FakeProgress())
    check("bulk loader reuses saved results, then splits six missing suburbs into batches of five and one", lambda:
          [len(batch) for batch in batch_calls] == [5, 1]
          and len(result) == 8 and synced == 6 and not errors
          and result.iloc[0]["Data source"] == "Supabase"
          and result.iloc[2]["Data source"] == "OpenStreetMap")
    check("bulk loader syncs only newly fetched counts", lambda:
          sum(len(payload) for payload in saved_payloads) == 6)

    with STARTER_LIST_PATH.open(encoding="utf-8-sig", newline="") as csv_file:
        starter_rows = list(csv.DictReader(csv_file))
    starter_names = [row.get("suburb", "").strip().casefold() for row in starter_rows]
    check("60-suburb starter CSV has a suburb column and no more than 60 unique entries", lambda:
          bool(starter_rows) and len(starter_rows) <= 60
          and all(starter_names) and len(starter_names) == len(set(starter_names)))

    app_source = APP_PATH.read_text(encoding="utf-8")
    check("buyer snapshot shows named suburbs and their pair-relative scores", lambda:
          'st.subheader("Buyer snapshot")' in app_source
          and '"Suburb": suburb_a["suburb"]' in app_source
          and '"Score": overall_a' in app_source
          and "st.altair_chart" in app_source)


def stage_e() -> None:
    edge_data = [
        {"type": "node", "id": 1, "lat": 1.0, "lon": 1.0, "tags": {"leisure": "park"}},
        {"type": "node", "id": 2, "lat": 1.000001, "lon": 1.0, "tags": {"leisure": "garden"}},
        {"type": "way", "id": 3, "center": {"lat": 0.0, "lon": 0.0}, "tags": {"leisure": "playground"}},
    ]
    class FakeSession:
        def post(self, *args, **kwargs):
            return FakeOverpassResponse(edge_data)
    fetch, _ = app_function(
        "fetch_osm_batch", session=FakeSession(), OVERPASS_ENDPOINTS=("https://overpass.example/api",),
    )
    counts = fetch((("Extent, NSW", 0, 0, 1, 1),))
    check("bounding-box filter includes its edges and excludes a feature just outside", lambda:
          counts == {"Extent, NSW": 2})

    app_source = APP_PATH.read_text(encoding="utf-8").casefold()
    readme = (ROOT / "README.md").read_text(encoding="utf-8").casefold()
    check("app and README disclose that CSV rectangles approximate SAL polygons", lambda:
          "not the actual sal polygon" in app_source and "extent approximation" in app_source
          and "not sal polygon geometry" in readme
          and "include places outside the actual suburb" in readme)


def stage_f() -> None:
    from livability import weighting

    prompt = "I have a toddler and no car."
    sample = '{"weights":[{"kpi":"parks","weight":9,"reason":"prefers parks"}]}'
    valid = weighting.suggest_weights(prompt, "test-key", ask=lambda *_: sample)
    fallback = weighting.suggest_weights(prompt, "test-key", ask=lambda *_: "invalid",
                                         kpis=weighting.PARKS_MEASURES)
    check("Stage F prompt contains the preferences and asks for JSON", lambda:
          prompt in weighting.build_prompt(prompt) and "JSON" in weighting.build_prompt(prompt))
    check("Groq output is validated and clamped to 0–5", lambda:
          valid.source == "ai" and valid.weights["parks"] == 5 and valid.weights["transport"] == 3)
    check("Toddler and no car set park density weight with keyword fallback", lambda:
          fallback.source == "keywords" and fallback.weights == {"parks_total": 3, "parks": 5})
    check("Personal score is the weighted average of available measures", lambda:
          weighting.personal_score({"parks_total": 100, "parks": 40}, {"parks_total": 1, "parks": 3}) == 55
          and weighting.personal_score({"parks": None}, {"parks": 5}) is None
          and weighting.personal_score({"parks": 50}, {"parks": 0}) is None)


STAGES = {"A": stage_a, "B": stage_b, "C": stage_c, "D": stage_d, "E": stage_e, "F": stage_f}


def main() -> int:
    stage = sys.argv[1].upper() if len(sys.argv) > 1 else ""
    if stage == "ALL":
        selected = list(STAGES.items())
    elif stage in STAGES:
        selected = [(stage, STAGES[stage])]
    else:
        print("Usage: python check.py A   (or B, C, D, E, F or ALL)")
        return 2
    global failures, checks_run
    failures = checks_run = 0
    print("Demografy project checks (offline; mocked API/database responses)")
    for letter, stage_func in selected:
        before = failures
        checks_before = checks_run
        print(f"\nStage {letter}")
        stage_func()
        stage_failures = failures - before
        print(f"Stage {letter}: {checks_run - checks_before} checks, {stage_failures} failure(s)")
        if stage_failures:
            break
    print(f"\nTotal: {checks_run} checks, {failures} failure(s)")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
