import json
import io
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from handwriting_grader.azure_ai import Usage, normalize_usage
from handwriting_grader.telemetry import TelemetryTracker, get_thinking_config


class TestAzureTelemetry(unittest.TestCase):
    def test_progress_supports_windows_legacy_encoding(self):
        stream = io.TextIOWrapper(io.BytesIO(), encoding="cp1252")
        with redirect_stdout(stream):
            TelemetryTracker().show_progress("metadata_ocr", 1, 2, "Script #1")
        stream.flush()
        self.assertIn(b"Script #1", stream.buffer.getvalue())

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

    def test_small_embedding_calls_are_not_rounded_away_before_aggregation(self):
        tracker = TelemetryTracker()
        tracker.rates_table = {"embedding": {"input": 0.02}}
        tracker.record_call("embedding", "question", "embedding", Usage(10, 0, 10), 1)
        self.assertAlmostEqual(tracker.get_summary()["total_cost_usd"], 0.0000002, places=12)
        for _ in range(99):
            tracker.record_call("embedding", "question", "embedding", Usage(10, 0, 10), 1)
        summary = tracker.get_summary()
        self.assertAlmostEqual(summary["total_cost_usd"], 0.00002)
        self.assertAlmostEqual(summary["by_phase"]["embedding"]["cost_usd"], 0.00002)
        self.assertAlmostEqual(summary["by_model"]["embedding"]["cost_usd"], 0.00002)
        with tempfile.TemporaryDirectory() as temp:
            from openpyxl import load_workbook

            root = Path(temp)
            tracker.write_cost_report(root)
            self.assertAlmostEqual(json.loads((root / "cost_summary.json").read_text())["total_cost_usd"], 0.00002)
            workbook = load_workbook(root / "cost_report.xlsx", data_only=True)
            self.assertAlmostEqual(workbook["API Audit Log"]["K2"].value, 0.0000002, places=12)
            self.assertAlmostEqual(workbook["Summary"]["G2"].value, 0.00002)
            workbook.close()

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

    def test_long_context_and_cache_writes_are_priced_without_double_counting(self):
        tracker = TelemetryTracker()
        tracker.rates_table = {"grader": {
            "long_context_threshold": 272_000,
            "short": {"input": 2, "cached": 0.1, "output": 10, "cache_write": 2.5, "cache_write_12h": 5},
            "long": {"input": 4, "cached": 0.2, "output": 15, "cache_write": 5, "cache_write_12h": 10},
        }}
        for tokens, ttl, expected in ((272_000, "30m", 0.389), (272_001, "30m", 0.773004),
                                      (272_000, "12h", 0.514)):
            with self.subTest(tokens=tokens, ttl=ttl):
                trace = tracker.record_call(
                    "grading", "Q1", "grader",
                    Usage(tokens, 1000, tokens + 1000, 100_000, 0, 50_000, ttl), 1,
                )
                self.assertTrue(trace.cost_known)
                self.assertEqual(trace.cost_usd, expected)
        with tempfile.TemporaryDirectory() as temp:
            from openpyxl import load_workbook
            target = Path(temp)
            tracker.write_cost_report(target)
            workbook = load_workbook(target / "cost_report.xlsx")
            try:
                sheet = workbook["API Audit Log"]
                columns = {cell.value: cell.column for cell in sheet[1]}
                self.assertEqual(sheet.cell(2, columns["Cache Write Tokens"]).value, 50_000)
                self.assertEqual(sheet.cell(2, columns["Cache Write TTL"]).value, "30m")
            finally:
                workbook.close()

    def test_missing_rates_write_usage_or_ttl_keep_cost_unknown(self):
        for rates, usage in (
            ({"input": 2}, Usage(100, 20, 120)),
            ({"input": 2, "output": 8}, Usage(100, 20, 120, 10)),
            ({"input": 2, "output": 8, "cache_write": 2.5}, Usage(100, 20, 120)),
            ({"input": 2, "output": 8, "cache_write": 2.5}, Usage(100, 20, 120, 0, 0, 50)),
            ({"input": 2, "output": 8, "cache_write": 2.5}, Usage(100, 20, 120, 0, 0, 50, "12h")),
            ({"input": float("nan"), "output": 8}, Usage(100, 20, 120)),
        ):
            with self.subTest(rates=rates, usage=usage):
                tracker = TelemetryTracker()
                tracker.rates_table = {"grader": rates}
                trace = tracker.record_call("grading", "Q1", "grader", usage, 1)
                self.assertFalse(trace.cost_known)
                self.assertIsNone(tracker.get_summary()["total_cost_usd"])

    def test_write_usage_normalization_preserves_missing_vs_zero(self):
        from types import SimpleNamespace
        missing = normalize_usage(SimpleNamespace(input_tokens=100, output_tokens=10))
        self.assertIsNone(missing.cache_write_token_count)
        for count in (0, 50):
            reported = normalize_usage(SimpleNamespace(
                input_tokens=100, output_tokens=10,
                input_tokens_details=SimpleNamespace(cached_tokens=10, cache_write_tokens=count),
            ), cache_write_ttl="30m")
            self.assertEqual(reported.cache_write_token_count, count)
            self.assertEqual(reported.cache_write_ttl, "30m")
