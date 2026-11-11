"""Outdoor benchmark and AI-assisted comparison."""

import requests

from pipeline import PARKS_KPI, SEARCH_VERSION, connect

CBD_NAMES = {
    "NSW": {"sydney", "sydney city", "parramatta", "newcastle", "wollongong"},
    "VIC": {"melbourne", "melbourne city", "geelong"},
    "QLD": {"brisbane", "brisbane city", "cairns", "townsville"},
    "WA": {"perth", "perth city"},
    "SA": {"adelaide", "adelaide city"},
    "TAS": {"hobart", "launceston"},
    "NT": {"darwin", "darwin city"},
    "ACT": {"canberra", "canberra city", "city", "civic"},
}
AI_MODEL = "openai/gpt-oss-20b"
AI_URL = "https://api.groq.com/openai/v1/chat/completions"
BENCHMARK_SUBURBS = {
    "NSW": ("Bondi", "Newtown", "Glebe", "Surry Hills"),
    "VIC": ("Carlton", "Fitzroy", "East Melbourne", "Canterbury"),
    "QLD": ("South Brisbane", "Gordon Park", "New Farm", "West End (Brisbane - Qld)"),
}


def is_cbd(name, state):
    words = name.casefold().replace("-", " ").replace("(", " ").replace(")", " ").split()
    return "cbd" in words or " ".join(words) in CBD_NAMES.get(state.strip().upper(), ())


def benchmark_candidates(catalogue):
    return [
        suburb for suburb in catalogue
        if suburb.suburb_name in BENCHMARK_SUBURBS.get(suburb.state, ())
        and not is_cbd(suburb.suburb_name, suburb.state)
    ]


def load_benchmark(database_url, candidates):
    with connect(database_url) as connection:
        rows = connection.execute("""
            select catalog.sal_code, catalog.suburb_name, catalog.state,
                   (metrics.counts ->> %s)::int as place_count,
                   (metrics.counts ->> %s)::float8 / catalog.area_km2 as density
            from livability.amenity_metrics as metrics
            join livability.suburb_catalog as catalog using (sal_code)
            where metrics.search_version = %s and catalog.sal_code = any(%s)
              and catalog.area_km2 > 0
              and metrics.refreshed_at + interval '1 month' > statement_timestamp()
              and metrics.bounds = jsonb_build_object(
                  'low', jsonb_build_object('latitude', catalog.min_lat, 'longitude', catalog.min_lon),
                  'high', jsonb_build_object('latitude', catalog.max_lat, 'longitude', catalog.max_lon)
              )
        """, (PARKS_KPI, PARKS_KPI, SEARCH_VERSION, [suburb.sal_code for suburb in candidates])).fetchall()
    sample = {row["sal_code"]: row for row in rows if row["density"] is not None
              and not is_cbd(row["suburb_name"], row["state"])}
    if len(sample) < sum(map(len, BENCHMARK_SUBURBS.values())):
        return None, None, len(sample), None
    winner = max(sample.values(), key=lambda row: (row["density"], row["sal_code"]))
    max_count = max(row["place_count"] for row in sample.values())
    return winner["density"] or None, f"{winner['suburb_name']}, {winner['state']}", len(sample), max_count


def rating(score):
    if score >= 90:
        return "Excellent"
    if score >= 70:
        return "Good"
    if score >= 40:
        return "Fair"
    return "Poor"


def ai_completion(api_key, system, prompt):
    payload = {
        "model": AI_MODEL,
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": prompt}],
        "reasoning_effort": "low",
        "max_completion_tokens": 1800,
        "tools": [{"type": "browser_search"}],
        "tool_choice": "required",
    }
    try:
        response = requests.post(
            AI_URL, headers={"Authorization": f"Bearer {api_key}"}, json=payload, timeout=(4, 40),
        )
        response.raise_for_status()
        content = response.json()["choices"][0]["message"]["content"]
        if not isinstance(content, str) or not content.strip():
            raise ValueError
        return content
    except (requests.RequestException, KeyError, IndexError, TypeError, ValueError):
        raise ValueError("The AI service could not complete this request. Try again.") from None


def discover_places(api_key, interest):
    return ai_completion(
        api_key,
        "Search the web for popular outdoor places across Australia. Prefer official parks agencies and tourism "
        "boards, and use visitation evidence when available. Cover multiple states and territories. "
        "Give up to six places, their region, why they are popular, and a direct HTTPS source link per place. "
        "Avoid ranking places unless comparable visitation evidence supports the ranking. Return concise Markdown.",
        interest,
    )
