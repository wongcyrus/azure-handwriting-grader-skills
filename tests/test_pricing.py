import contextlib
import copy
import io
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import Mock, patch

import yaml

from handwriting_grader.cli import main
from handwriting_grader.pricing import RETAIL_API, configured_models, lookup_pricing, write_priced_config
from handwriting_grader.telemetry import load_pricing_rates


NOW = datetime(2026, 11, 23, tzinfo=timezone.utc)


def meter(sku, price, **overrides):
    return {
        "productName": "Azure OpenAI GPT6", "serviceName": "Foundry Models",
        "skuName": sku, "meterName": f"{sku} 1M Tokens", "meterId": f"synthetic-{sku}",
        "currencyCode": "USD", "armRegionName": "eastus", "type": "Consumption",
        "unitOfMeasure": "1M", "tierMinimumUnits": 0,
        "retailPrice": price, "effectiveStartDate": "2026-11-01T00:00:00Z",
        **overrides,
    }


def standard_meters(family="6.2-sol"):
    return [
        meter(f"{family} {context} {kind} Std Gl", price)
        for context, multiplier in (("ShCo", 1), ("LoCo", 2))
        for kind, price in (("Inp", 2 * multiplier), ("Cd Inp", 0.1 * multiplier),
                            ("Opt", 10 if multiplier == 1 else 15), ("Cd Wr", 2.5 * multiplier))
    ] + [meter(f"{family} {context} Cd Wr 12hr Gl", price)
         for context, price in (("ShCo", 5), ("LoCo", 10))]


class TestRetailPricing(unittest.TestCase):
    def lookup(self, rows, **kwargs):
        return lookup_pricing(
            "eastus", "global-standard", {"private-grader": "gpt-6.2-sol"},
            fetch_page=lambda url: {"Items": rows, "NextPageLink": None}, now=NOW, **kwargs,
        )

    def test_exact_matching_excludes_other_regions_models_modes_and_future_prices(self):
        rows = standard_meters()
        rows += [
            meter("6.2-sol ShCo Inp Flex Gl", 1),
            meter("6.2-sol ShCo Inp Std DZ", 2.2),
            meter("6.2-sol ShCo Inp Std Gl", 99, armRegionName="westeurope"),
            meter("6.2-sol ShCo Inp Std Gl", 99, effectiveStartDate="2027-01-01T00:00:00Z"),
            meter("6.2-astra ShCo Inp Std Gl", 8),
            meter("6.2-sol ShCo Inp Std Gl", 99, currencyCode="EUR"),
        ]
        report = self.lookup(rows)
        entry = report["deployments"]["private-grader"]
        self.assertEqual(entry["status"], "PRICED")
        self.assertEqual(entry["tiers"]["short"]["input"], 2)
        self.assertEqual(entry["tiers"]["long"]["input"], 4)
        self.assertEqual(entry["tiers"]["short"]["cache_write_12h"], 5)
        self.assertEqual(entry["meters"]["short"]["input"]["sku_name"], "6.2-sol ShCo Inp Std Gl")
        self.assertNotIn("private-grader", report["source"])

    def test_terra_abbreviations_and_data_zone_are_matched(self):
        rows = [meter(item["skuName"].replace("6.2-sol", "61 terra").replace("Gl", "DZ"),
                      item["retailPrice"]) for item in standard_meters()]
        for item in rows:
            if "12hr" in item["skuName"]:
                item["skuName"] = item["skuName"].replace("61 terra", "61terra")
        report = lookup_pricing(
            "eastus", "data-zone-standard", {"vision": "gpt-6.1-terra"},
            fetch_page=lambda url: {"Items": rows}, now=NOW,
        )
        self.assertEqual(report["deployments"]["vision"]["status"], "PRICED")
        self.assertEqual(report["deployments"]["vision"]["tiers"]["long"]["cache_write_12h"], 10)

    def test_latest_effective_meter_and_per_thousand_units_are_normalized(self):
        rows = standard_meters()
        rows.append(meter("6.2-sol ShCo Inp Std Gl", 0.003, unitOfMeasure="1K",
                          effectiveStartDate="2026-11-15T00:00:00Z", meterId="new-meter"))
        report = self.lookup(rows)
        self.assertEqual(report["deployments"]["private-grader"]["tiers"]["short"]["input"], 3)

    def test_sol_and_luna_twelve_hour_shorthand_matches_without_using_flex(self):
        for model, family, shorthand in (("gpt-6.1-sol", "6.1-sol", "61sol"),
                                         ("gpt-6-luna", "6-luna", "6luna")):
            with self.subTest(model=model):
                rows = standard_meters(family)
                for item in rows:
                    if "12hr" in item["skuName"]:
                        item["skuName"] = item["skuName"].replace(family, shorthand)
                rows.append(meter(f"{shorthand} ShCo Cd Wr 12hr Fl Gl", 999))
                report = lookup_pricing(
                    "eastus", "global-standard", {"grader": model},
                    fetch_page=lambda url: {"Items": rows}, now=NOW,
                )
                entry = report["deployments"]["grader"]
                self.assertEqual(entry["tiers"]["short"]["cache_write_12h"], 5)
                self.assertEqual(entry["tiers"]["long"]["cache_write_12h"], 10)

    def test_missing_ambiguous_invalid_and_unsupported_prices_stay_unpriced(self):
        for extra in (
            None,
            meter("6.2-sol ShCo Inp Std Gl", 9, meterId="conflicting-meter"),
            meter("6.2-sol ShCo Inp Std Gl", -1, effectiveStartDate="2026-11-15T00:00:00Z"),
            meter("6.2-sol ShCo Inp Std Gl", 9, unitOfMeasure="1 Hour",
                  effectiveStartDate="2026-11-15T00:00:00Z"),
            meter("6.2-sol ShCo Inp Std Gl", float("nan"), effectiveStartDate="2026-11-15T00:00:00Z"),
        ):
            with self.subTest(extra=extra):
                rows = standard_meters()
                if extra is None:
                    rows = [item for item in rows if item["skuName"] != "6.2-sol ShCo Inp Std Gl"]
                else:
                    rows.append(extra)
                entry = self.lookup(rows)["deployments"]["private-grader"]
                self.assertEqual(entry["status"], "UNPRICED")
                self.assertIsNone(entry["tiers"]["short"]["input"])
                self.assertTrue(entry["issues"])

    def test_pagination_is_complete_and_never_leaves_microsoft(self):
        rows = standard_meters()
        fetch = Mock(side_effect=[
            {"Items": rows[:5], "NextPageLink": RETAIL_API + "?$skip=1000"},
            {"Items": rows[5:]},
        ])
        report = lookup_pricing("eastus", "global-standard", {"grader": "gpt-6.2-sol"},
                                fetch_page=fetch, now=NOW)
        self.assertEqual(report["pages_fetched"], 2)
        self.assertEqual(report["deployments"]["grader"]["status"], "PRICED")
        for link in ("https://example.test/prices", "http://prices.azure.com/api/retail/prices",
                     RETAIL_API + "?$skip=1000"):
            with self.subTest(link=link):
                fetch = Mock(return_value={"Items": [], "NextPageLink": link})
                with self.assertRaises(ValueError):
                    lookup_pricing("eastus", "global-standard", fetch_page=fetch, now=NOW)
                self.assertLessEqual(fetch.call_count, 2)

    def test_unsupported_family_does_not_make_network_requests_or_guess_rates(self):
        fetch = Mock()
        report = lookup_pricing("eastus", "global-standard", {"embed": "text-embedding-ada-002"},
                                fetch_page=fetch, now=NOW)
        fetch.assert_not_called()
        self.assertEqual(report["deployments"]["embed"]["status"], "UNPRICED")

    def test_unpriced_global_standard_profile_suggests_refreshed_known_meter_region(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output), \
                patch("handwriting_grader.pricing._fetch_page",
                      return_value={"Items": [], "NextPageLink": None}):
            main([
                "fetch-pricing", "--region", "eastasia",
                "--deployment-type", "global-standard",
            ])
        self.assertIn("--region eastus", output.getvalue())
        self.assertIn("no region was substituted", output.getvalue())

    def test_invalid_region_mode_and_malformed_pages_fail_before_any_snapshot(self):
        fetch = Mock()
        for region, mode in (("eastus' or true", "global-standard"), ("eastus", "batch")):
            with self.subTest(region=region), self.assertRaises(ValueError):
                lookup_pricing(region, mode, fetch_page=fetch)
        fetch.assert_not_called()
        with self.assertRaises(ValueError):
            lookup_pricing("eastus", "global-standard", fetch_page=lambda url: {"Items": "invalid"})

    def test_cli_exports_new_priced_config_without_overwrite_or_inference(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source, target = root / "models.yaml", root / "priced.yaml"
            config = {
                "azure_openai": {"endpoint": "https://school.openai.azure.com", "api_version": "v1"},
                "models": {"grading": "private-grader", "embedding": "private-embed"},
                "deployment_models": {"private-grader": "gpt-6.2-sol",
                                      "private-embed": "text-embedding-3-small"},
                "pricing": {"private-embed": {"input": 999}},
            }
            source.write_text(yaml.safe_dump(config))
            original = source.read_bytes()
            args = ["fetch-pricing", "--region", "eastus", "--deployment-type", "global-standard",
                    "--model-config", str(source), "--write-config", str(target)]
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()), \
                    patch("handwriting_grader.pricing._fetch_page", return_value={"Items": standard_meters()}) as fetch, \
                    patch("handwriting_grader.azure_ai.AzureClient", side_effect=AssertionError("No inference")):
                self.assertEqual(main(args), 0)
                self.assertEqual(main(args), 1)
            self.assertEqual(fetch.call_count, 2)
            self.assertEqual(source.read_bytes(), original)
            saved = yaml.safe_load(target.read_text())
            self.assertEqual(saved["models"], config["models"])
            self.assertEqual(saved["pricing"]["private-embed"], {})
            self.assertIn("fetched_at", saved["pricing_sources"]["private-grader"])
            with patch("pathlib.Path.home", return_value=root):
                rates = load_pricing_rates(target)
            self.assertEqual(rates["private-grader"]["short"]["input"], 2)
            self.assertEqual(rates["private-embed"], {})
            saved["deployment_models"]["private-grader"] = "gpt-6.1-terra"
            target.write_text(yaml.safe_dump(saved))
            with patch("pathlib.Path.home", return_value=root):
                self.assertEqual(load_pricing_rates(target)["private-grader"], {})

    def test_embedding_prices_require_exact_active_global_meter(self):
        sku = "text-embedding-3-small-glbl"
        row = meter(sku, 0.00002, productName="Azure OpenAI",
                    meterName=f"{sku} Tokens", unitOfMeasure="1K")
        rows = [row, {**row, "armRegionName": "westeurope", "retailPrice": 99}]
        report = lookup_pricing("eastus", "global-standard", {"embed": "text-embedding-3-small"},
                                fetch_page=lambda url: {"Items": rows}, now=NOW)
        entry = report["deployments"]["embed"]
        self.assertEqual(entry["status"], "PRICED")
        self.assertEqual(entry["input"], 0.02)
        rows.append({**row, "meterId": "conflict", "retailPrice": 1})
        report = lookup_pricing("eastus", "global-standard", {"embed": "text-embedding-3-small"},
                                fetch_page=lambda url: {"Items": rows}, now=NOW)
        self.assertEqual(report["deployments"]["embed"]["status"], "UNPRICED")

    def test_unpriced_export_blocks_stale_cache_and_preserves_source_configuration(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            config = {"azure_openai": {"endpoint": "https://school.openai.azure.com"},
                      "models": {"grading": "gpt-6.2-sol"}}
            original = copy.deepcopy(config)
            report = lookup_pricing("eastus", "global-standard", configured_models(config),
                                    fetch_page=lambda url: {"Items": []}, now=NOW)
            target = root / "new.yaml"
            write_priced_config(target, config, report)
            self.assertEqual(config, original)
            with self.assertRaises(FileExistsError):
                write_priced_config(target, config, report)
            with patch("pathlib.Path.home", return_value=root):
                self.assertEqual(load_pricing_rates(target)["gpt-6.2-sol"]["short"], {})
