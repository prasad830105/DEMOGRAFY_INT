"""Offline checks for the Livability v2 Google Places dashboard."""

import csv
import sys
import unittest
from pathlib import Path
from time import monotonic
from unittest.mock import patch

from google_boundary_pilot import coordinates_for_google
from livability.weighting import PARKS_MEASURES, personal_score, suggest_weights
from outdoor_analysis import benchmark_candidates, is_cbd, load_benchmark, rating
from pipeline import PARKS_KPI, Suburb, get_metrics, search_category

ROOT = Path(__file__).resolve().parent
BONDI = Suburb("SAL10462", "Bondi", "NSW", "2026", 0.8647, 10411,
               -33.89825, 151.2582, -33.88804, 151.27585)


class StageA(unittest.TestCase):
    def test_catalogue_and_kpi(self):
        with (ROOT / "suburbs.csv").open(encoding="utf-8-sig", newline="") as file:
            bondi = next(row for row in csv.DictReader(file) if row["sal_code"] == BONDI.sal_code)
        self.assertEqual(bondi["suburb_name"], BONDI.suburb_name)
        self.assertAlmostEqual(12 / float(bondi["area_km2"]), 13.88, places=2)
        self.assertEqual(PARKS_KPI, "Parks and outdoor places")
        self.assertEqual([rating(score) for score in (100, 70, 40, 39)],
                         ["Excellent", "Good", "Fair", "Poor"])


class StageB(unittest.TestCase):
    def test_cache_hit_reuses_snapshot_without_google(self):
        saved = {"counts": {PARKS_KPI: 12}, "refreshed_at": None}
        with patch("pipeline.connect") as connect, patch("pipeline.search_category") as search:
            connection = connect.return_value.__enter__.return_value
            connection.execute.return_value.fetchone.return_value = saved
            result = get_metrics("test-db", "test-key", BONDI, monotonic() + 5)
        search.assert_not_called()
        self.assertEqual(result, {**saved, "source": "Supabase cache"})
        self.assertIn("interval '1 month'", connection.execute.call_args.args[0])


class StageC(unittest.TestCase):
    def test_google_pagination_deduplicates_ids(self):
        requests = []
        with patch("pipeline.requests.Session") as session:
            response = session.return_value.__enter__.return_value.post.return_value

            def page(url, *, json, headers, timeout):
                requests.append((json.copy(), headers))
                return response

            session.return_value.__enter__.return_value.post.side_effect = page
            response.json.side_effect = [
                {"places": [{"id": "a"}], "nextPageToken": "page-2"},
                {"places": [{"id": "a"}, {"id": "b"}]},
            ]
            ids = search_category(BONDI, "parks", "test-key", monotonic() + 5)
        self.assertEqual(ids, ["a", "b"])
        self.assertEqual(requests[1][0]["pageToken"], "page-2")
        self.assertEqual(requests[0][0]["locationRestriction"], {"rectangle": BONDI.rectangle})
        self.assertEqual(requests[0][1]["X-Goog-FieldMask"], "places.id,nextPageToken")


class StageD(unittest.TestCase):
    def test_cbd_excluded_and_highest_density_sets_benchmark(self):
        cbd = Suburb("CBD", "Brisbane City", "QLD", None, 1, None, -1, 1, 0, 2)
        self.assertTrue(is_cbd(cbd.suburb_name, cbd.state))
        self.assertEqual(benchmark_candidates([BONDI, cbd]), [BONDI])
        rows = [
            {"sal_code": str(i), "suburb_name": f"Sample {i}", "state": "NSW",
             "density": float(i), "place_count": i}
            for i in range(1, 13)
        ]
        rows.append({"sal_code": cbd.sal_code, "suburb_name": cbd.suburb_name,
                     "state": cbd.state, "density": 999, "place_count": 999})
        with patch("outdoor_analysis.connect") as connect:
            connect.return_value.__enter__.return_value.execute.return_value.fetchall.return_value = rows
            self.assertEqual(load_benchmark("test-db", [BONDI]), (12.0, "Sample 12, NSW", 12, 12))


class StageE(unittest.TestCase):
    def test_polygon_pilot_formats_closed_counterclockwise_ring(self):
        clockwise = [[0, 0], [0, 2], [1, 0], [0, 0]]
        self.assertEqual(coordinates_for_google({"type": "Polygon", "coordinates": [clockwise]}), [
            {"latitude": 0, "longitude": 0},
            {"latitude": 0, "longitude": 1},
            {"latitude": 2, "longitude": 0},
            {"latitude": 0, "longitude": 0},
        ])


class StageF(unittest.TestCase):
    def test_keyword_fallback_after_invalid_ai_response(self):
        result = suggest_weights("I have a toddler and no car.", "test-key",
                                 ask=lambda *_: "invalid", kpis=PARKS_MEASURES)
        self.assertEqual(result.source, "keywords")
        self.assertEqual(result.weights, {"parks_total": 3, "parks": 5})

    def test_ai_weight_validation_and_personal_score(self):
        answer = '{"weights":[{"kpi":"parks","weight":9,"reason":"prefers concentration"}]}'
        result = suggest_weights("parks close together", "test-key",
                                 ask=lambda *_: answer, kpis=PARKS_MEASURES)
        self.assertEqual(result.source, "ai")
        self.assertEqual(result.weights, {"parks_total": 3, "parks": 5})
        self.assertEqual(personal_score({"parks_total": 100, "parks": 40},
                                       {"parks_total": 1, "parks": 3}), 55)
        self.assertIsNone(personal_score({"parks": 50}, {"parks": 0}))


if __name__ == "__main__":
    stages = dict(zip("ABCDEF", (StageA, StageB, StageC, StageD, StageE, StageF), strict=True))
    selected = sys.argv[1].upper() if len(sys.argv) == 2 else ""
    if selected != "ALL" and selected not in stages:
        raise SystemExit("Usage: python check.py A (or B, C, D, E, F or ALL)")
    for letter in stages if selected == "ALL" else (selected,):
        print(f"Stage {letter}", flush=True)
        suite = unittest.defaultTestLoader.loadTestsFromTestCase(stages[letter])
        if not unittest.TextTestRunner(verbosity=2, failfast=True).run(suite).wasSuccessful():
            raise SystemExit(1)
