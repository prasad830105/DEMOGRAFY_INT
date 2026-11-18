"""Offline checks for the Parks and Outdoor Spaces comparison."""

import csv
import sys
import unittest
from copy import deepcopy
from pathlib import Path
from time import monotonic
from unittest.mock import Mock, patch

from boundary_store import ensure_boundary_measurement
from google_boundary_pilot import coordinates_for_google
from outdoor_analysis import (
    benchmark_candidates, benchmark_score, load_benchmark, rating, suggest_weight, weighted_outdoor_score,
)
from pipeline import PARKS_KPI, PARKS_SEARCH_TYPES, Suburb, get_metrics, search_suburb


SUBURB = Suburb("test", "Test suburb", "NSW", None, 1.0, None, -34, 150, -30, 154)
BONDI = Suburb("SAL10462", "Bondi", "NSW", "2026", 0.8647, 10411,
               -33.89825, 151.2582, -33.88804, 151.27585)


def bounds(rectangle):
    low, high = rectangle["low"], rectangle["high"]
    return low["latitude"], low["longitude"], high["latitude"], high["longitude"]


class StageA(unittest.TestCase):
    def test_suburb_area_is_used_to_scale_density(self):
        packaged_csv = Path(__file__).with_name("suburbs.csv")
        with packaged_csv.open(encoding="utf-8-sig", newline="") as file:
            bondi = next(row for row in csv.DictReader(file) if row["sal_code"] == BONDI.sal_code)
        self.assertEqual(bondi["suburb_name"], BONDI.suburb_name)
        self.assertAlmostEqual(benchmark_score(12 / float(bondi["area_km2"]), 20), 69.39, places=2)


class StageB(unittest.TestCase):
    def test_fresh_snapshot_skips_google_and_miss_saves_result(self):
        saved = {"counts": {PARKS_KPI: 1}, "refreshed_at": None, "search_capped": False}
        with patch("pipeline.connect") as connect, patch("pipeline.search_suburb") as search:
            connection = connect.return_value.__enter__.return_value
            cursor = connection.execute.return_value
            cursor.fetchone.return_value = saved
            cached = get_metrics("test-db", "test-key", BONDI, monotonic() + 5)
            self.assertEqual(cached, {**saved, "source": "Supabase cache"})
            self.assertIn("interval '1 month'", connection.execute.call_args.args[0])
            search.assert_not_called()

            cursor.fetchone.side_effect = [None, None, saved]
            search.return_value = (["place-a"], False)
            fresh = get_metrics("test-db", "test-key", BONDI, monotonic() + 5)
            self.assertEqual(fresh, {**saved, "source": "Google Maps"})
            search.assert_called_once()
            writes = [call.args for call in connection.execute.call_args_list
                      if "insert into livability.place_snapshots" in call.args[0]]
            self.assertEqual(len(writes), 1)
            self.assertEqual(writes[0][1][3].obj, {PARKS_KPI: ["place-a"]})


class StageC(unittest.TestCase):
    def test_google_pagination_deduplicates_across_pages(self):
        def post(url, *, json, headers, timeout):
            self.assertEqual(headers["X-Goog-FieldMask"], "places.id,nextPageToken")
            self.assertEqual(json["locationRestriction"], {"rectangle": BONDI.rectangle})
            response = Mock()
            if json["includedType"] != "park":
                payload = {"places": [{"id": "a"}]}
            elif json.get("pageToken") == "second":
                payload = {"places": [{"id": "a"}, {"id": "b"}]}
            else:
                payload = {"places": [{"id": "a"}], "nextPageToken": "second"}
            response.json.return_value = payload
            return response

        with patch("pipeline.requests.Session.post", side_effect=post) as search:
            self.assertEqual(search_suburb(BONDI, "test-key", monotonic() + 5), (["a", "b"], False))
        self.assertEqual(search.call_count, len(PARKS_SEARCH_TYPES) + 1)


class StageD(unittest.TestCase):
    def test_saturated_search_subdivides_twice_and_deduplicates_all_ids(self):
        root = (-34, 150, -30, 154)
        southwest = (-34, 150, -32, 152)
        smallest = (-34, 150, -33, 151)
        requests_sent = []

        def post(url, *, json, headers, timeout):
            requests_sent.append((deepcopy(json), headers.copy()))
            rectangle = bounds(json["locationRestriction"]["rectangle"])
            place_type = json["includedType"]
            page = int(json.get("pageToken", "0"))
            response = Mock()
            if place_type == "park" and rectangle in {root, southwest, smallest}:
                # All three root pages repeat IDs. The 60 returned rows still trigger splitting.
                prefix = {root: "root", southwest: "quarter", smallest: "leaf"}[rectangle]
                offset = 0 if rectangle == root else 20 * page
                ids = [f"{prefix}-{i}" for i in range(offset, offset + 20)]
                next_page = {"nextPageToken": str(page + 1)} if page < 2 else {}
            else:
                ids = ["root-0", "shared"]
                next_page = {}
            response.json.return_value = {"places": [{"id": value} for value in ids], **next_page}
            return response

        with patch("pipeline.requests.Session.post", side_effect=post):
            ids, capped = search_suburb(SUBURB, "mock-key", monotonic() + 10)

        rectangles = {
            bounds(body["locationRestriction"]["rectangle"])
            for body, _ in requests_sent if body["includedType"] == "park"
        }
        self.assertEqual(rectangles, {
            root, southwest, (-34, 152, -32, 154), (-32, 150, -30, 152), (-32, 152, -30, 154),
            smallest, (-34, 151, -33, 152), (-33, 150, -32, 151), (-33, 151, -32, 152),
        })
        self.assertEqual({
            bounds(body["locationRestriction"]["rectangle"])
            for body, _ in requests_sent if body["includedType"] != "park"
        }, {root})
        self.assertEqual({body["includedType"] for body, _ in requests_sent}, set(PARKS_SEARCH_TYPES))
        self.assertEqual(len(requests_sent), 17)
        self.assertEqual({headers["X-Goog-FieldMask"] for _, headers in requests_sent}, {"places.id,nextPageToken"})
        self.assertEqual(len(ids), 141)
        self.assertEqual(ids.count("root-0"), 1)
        self.assertEqual(ids.count("shared"), 1)
        self.assertTrue(capped)

    def test_unsaturated_search_does_not_split(self):
        response = Mock()
        response.json.return_value = {"places": [{"id": "shared"}]}
        with patch("pipeline.requests.Session.post", return_value=response) as post:
            self.assertEqual(search_suburb(SUBURB, "mock-key", monotonic() + 10), (["shared"], False))
        self.assertEqual(post.call_count, len(PARKS_SEARCH_TYPES))

    def test_pathway_score_ranges_and_cap(self):
        scores = (0, 24, 25, 49, 50, 74, 75, 100)
        expected = ("Limited", "Limited", "Fair", "Fair", "Good", "Good", "Excellent", "Excellent")
        self.assertEqual(tuple(map(rating, scores)), expected)
        self.assertEqual(benchmark_score(40, 80), 50)
        self.assertEqual(benchmark_score(90, 80), 100)

    def test_highest_sample_density_excludes_cbd(self):
        cbd = Suburb("CBD", "Brisbane City", "QLD", None, 1, None, -1, 1, 0, 2)
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
    def test_boundary_is_sent_as_a_closed_counterclockwise_ring(self):
        polygon = {"type": "Polygon", "coordinates": [[[0, 0], [0, 2], [1, 0], [0, 0]]]}
        coordinates = [
            {"latitude": 0, "longitude": 0},
            {"latitude": 0, "longitude": 1},
            {"latitude": 2, "longitude": 0},
            {"latitude": 0, "longitude": 0},
        ]
        self.assertEqual(coordinates_for_google(polygon), coordinates)
        with (
            patch("boundary_store.connect") as connect,
            patch("boundary_store.fresh_results", side_effect=[{}, {}]),
            patch("boundary_store.load_boundaries", return_value={"10462": polygon}),
            patch("boundary_store.count_inside_boundary", return_value=0) as count,
        ):
            self.assertIsNone(ensure_boundary_measurement("test-db", "test-key", BONDI))
        count.assert_called_once_with("test-key", coordinates)
        connection = connect.return_value.__enter__.return_value
        connection.execute.assert_called_with("select livability.store_boundary_count(%s, %s)", (BONDI.sal_code, 0))

    def test_cached_boundary_does_not_call_abs_or_google(self):
        with (
            patch("boundary_store.connect"),
            patch("boundary_store.fresh_results", return_value={BONDI.sal_code: True}),
            patch("boundary_store.load_boundaries") as load,
            patch("boundary_store.count_inside_boundary") as count,
        ):
            self.assertIsNone(ensure_boundary_measurement("test-db", "", BONDI))
        load.assert_not_called()
        count.assert_not_called()


class StageF(unittest.TestCase):
    def test_ai_weight_changes_personal_score(self):
        with patch("outdoor_analysis.ai_completion", return_value={"total_weight": 75, "explanation": "More parks"}):
            weight, explanation = suggest_weight("test-key", "I want a larger number of parks")
        self.assertEqual(explanation, "More parks")
        self.assertEqual(weighted_outdoor_score(8, 4, 8, 8, weight), 87.5)

    def test_invalid_ai_weight_is_rejected(self):
        with patch("outdoor_analysis.ai_completion", return_value={"total_weight": 101}):
            with self.assertRaisesRegex(ValueError, "invalid weight"):
                suggest_weight("test-key", "I want more parks")


if __name__ == "__main__":
    checks = dict(zip("ABCDEF", (StageA, StageB, StageC, StageD, StageE, StageF), strict=True))
    selected = sys.argv[1].upper() if len(sys.argv) == 2 else ""
    if selected != "ALL" and selected not in checks:
        raise SystemExit("Usage: python check.py ALL (or choose A, B, C, D, E or F)")
    cases = checks.values() if selected == "ALL" else [checks[selected]]
    suite = unittest.TestSuite(unittest.defaultTestLoader.loadTestsFromTestCase(case) for case in cases)
    raise SystemExit(not unittest.TextTestRunner(verbosity=2).run(suite).wasSuccessful())
