#!/usr/bin/env python3

from __future__ import annotations

import unittest

import recover_hariharan_timing as script


class HariharanBoundedRecoveryTests(unittest.TestCase):
    def blocked_packet(self) -> dict:
        starts = {
            "occ-045": 361.969, "occ-048": 377.920,
            "occ-141": 1323.350, "occ-144": 1367.130, "occ-145": 1377.270,
            "occ-178": 1790.950, "occ-180": 1800.764,
            "occ-228": 2234.290, "occ-230": 2249.406,
        }
        return {
            "publication_status": "blocked",
            "validation_errors": [f"{value}: single start lacks agreeing evidence" for value in
                                  ("occ-046", "occ-047", "occ-142", "occ-144", "occ-179", "occ-229")],
            "refinements": [{"starts": [{"occurrence_id": key, "start": value}], "uncertain_ids": []}
                            for key, value in starts.items()],
            "ordered_occurrences": [{"occurrence_id": key, "source_text": key} for key in starts] + [
                {"occurrence_id": value, "source_text": value}
                for value in ("occ-046", "occ-047", "occ-142", "occ-179", "occ-229")
            ],
        }

    def test_dry_plan_is_exactly_eight_calls(self) -> None:
        plan = script.dry_run_plan(self.blocked_packet())
        self.assertEqual(plan["network_calls"], 0)
        self.assertEqual(plan["exact_future_audio_calls"], 8)
        self.assertEqual([entry["targets"] for entry in plan["recoveries"]], [
            ["occ-046", "occ-047"], ["occ-142"], ["occ-179"], ["occ-229"],
        ])

    def test_rejects_result_outside_neighbour_bracket(self) -> None:
        spec = script.RECOVERIES[2]  # occ-179 is tightly bracketed
        with self.assertRaisesRegex(RuntimeError, "outside accepted neighbour bracket"):
            script.validate_attempt(spec, {"starts": [{
                "occurrence_id": "occ-179", "status": "found", "start": 0.5, "uncertainty": "",
            }]})

    def test_requires_two_close_measurements(self) -> None:
        spec = script.RECOVERIES[0]
        first = {
            "occ-046": {"status": "found", "start": 367.4},
            "occ-047": {"status": "found", "start": 372.6},
        }
        second = {
            "occ-046": {"status": "found", "start": 367.7},
            "occ-047": {"status": "found", "start": 372.7},
        }
        consensus = script.two_pass_consensus(spec, [first, second])
        self.assertEqual(consensus["occ-046"]["start"], 367.55)
        self.assertEqual(consensus["occ-047"]["start"], 372.65)
        second["occ-047"]["start"] = 373.2
        with self.assertRaisesRegex(RuntimeError, "differ by more than 0.5s"):
            script.two_pass_consensus(spec, [first, second])

    def test_not_sung_is_only_allowed_for_142(self) -> None:
        disallowed = script.RECOVERIES[2]
        with self.assertRaisesRegex(RuntimeError, "not permitted"):
            script.validate_attempt(disallowed, {"starts": [{
                "occurrence_id": "occ-179", "status": "not_sung", "start": -1, "uncertainty": "",
            }]})
        allowed = script.RECOVERIES[1]
        result = script.validate_attempt(allowed, {"starts": [{
            "occurrence_id": "occ-142", "status": "not_sung", "start": -1, "uncertainty": "",
        }]})
        self.assertIsNone(result["occ-142"]["start"])


if __name__ == "__main__":
    unittest.main()
