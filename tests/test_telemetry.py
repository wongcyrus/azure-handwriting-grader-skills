import json
import tempfile
import unittest
from pathlib import Path

from handwriting_grader.azure_ai import Usage
from handwriting_grader.telemetry import TelemetryTracker, get_thinking_config


class TestAzureTelemetry(unittest.TestCase):
    def test_verified_rates_account_for_cached_tokens(self):
        tracker = TelemetryTracker()
        tracker.rates_table = {"school-grader": {"input": 2, "output": 8, "cached": 0.5}}
        self.assertEqual(tracker.calculate_cost("school-grader", 1_000_000, 100_000, 500_000), 2.05)
        trace = tracker.record_call("grading", "Q1", "school-grader",
                                    Usage(100, 20, 120, 10, 0), 1)
        self.assertTrue(trace.cost_known)
        self.assertGreater(tracker.get_summary()["total_cost_usd"], 0)

    def test_unknown_prices_are_not_reported_as_free(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            tracker = TelemetryTracker(log_dir=root)
            tracker.record_call("grading", "Q1", "unpriced-deployment", Usage(100, 20, 120), 1)
            summary = tracker.get_summary()
            self.assertIsNone(summary["total_cost_usd"])
            self.assertIsNone(summary["by_phase"]["grading"]["cost_usd"])
            self.assertEqual(summary["unpriced_calls"], 1)
            tracker.write_cost_report(root)
            self.assertIsNone(json.loads((root / "cost_summary.json").read_text())["total_cost_usd"])
            self.assertTrue((root / "azure_usage.jsonl").is_file())

    def test_missing_usage_keeps_cost_unknown(self):
        tracker = TelemetryTracker()
        tracker.rates_table = {"school-grader": {"input": 2, "output": 8}}
        tracker.record_call("images", "class", "school-grader", None, 1)
        self.assertIsNone(tracker.get_summary()["total_cost_usd"])

    def test_reasoning_is_not_forced_on_arbitrary_deployment_aliases(self):
        self.assertIsNone(get_thinking_config("school-grader"))
        self.assertIsNone(get_thinking_config("gpt-4.1"))
        self.assertEqual(get_thinking_config("gpt-5.4").effort, "medium")
        self.assertEqual(get_thinking_config("gpt-5.4", is_reasoning=False).effort, "low")
