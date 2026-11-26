import copy
import json
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import yaml

from handwriting_grader.azure_ai import AzureClient, GenerationConfig
from handwriting_grader.pricing import (
    PriceVerificationError, RunPricingVerifier, configured_models, lookup_pricing, write_priced_config,
    pricing_client_options,
)
from handwriting_grader.telemetry import TelemetryTracker, get_active_tracker, set_active_tracker
from test_pricing import NOW, meter, standard_meters


ENDPOINT = "https://school.openai.azure.com"


class TestFirstUsePrices(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.addCleanup(set_active_tracker, get_active_tracker())
        set_active_tracker(None)
        self.rows = standard_meters() + standard_meters("61 terra")

    def native_config(self, name="models.yaml"):
        config = {
            "azure_openai": {"endpoint": ENDPOINT},
            "models": {"grading": "grade-alias", "ocr": "ocr-alias"},
            "deployment_models": {"grade-alias": "gpt-6.2-sol", "ocr-alias": "gpt-6.1-terra"},
        }
        report = lookup_pricing(
            "eastus", "global-standard", configured_models(config),
            fetch_page=lambda url: {"Items": self.rows}, now=NOW,
        )
        path = self.root / name
        return path, write_priced_config(path, config, report)

    def verifier(self, path, rows=None):
        fetch = Mock(return_value={"Items": self.rows if rows is None else rows})
        verifier = RunPricingVerifier(path, self.root / "telemetry", fetch_page=fetch, now=lambda: NOW)
        return verifier, fetch

    def manual_config(self, role, family):
        config = {
            "azure_openai": {"endpoint": ENDPOINT},
            "models": {role: "manual-alias"}, "deployment_models": {"manual-alias": family},
            "pricing_lookup": {"region": "eastus", "deployment_type": "global-standard"},
            "pricing": {"manual-alias": {"input": 0.02, "cached": 0.01, "output": 8, "image": 0.1}},
            "pricing_sources": {"manual-alias": {
                "model": family, "verification": "manual", "verified_at": NOW.isoformat(),
                "region": "eastus", "deployment_type": "global-standard", "currency": "USD",
                "azure_endpoint": ENDPOINT, "unit": "USD per million tokens",
                "source": "https://azure.microsoft.com/en-us/pricing/details/azure-openai/",
            }},
        }
        path = self.root / "manual.yaml"
        path.write_text(yaml.safe_dump(config))
        return path, config

    def test_prices_precede_sdk_and_are_shared_across_clients_threads_and_models(self):
        path, _ = self.native_config()
        tracker = TelemetryTracker(self.root / "telemetry", path)
        tracker.pricing_verifier._now = lambda: NOW
        set_active_tracker(tracker)
        events = []
        fetch = Mock(side_effect=lambda url: events.append("prices") or {"Items": self.rows})
        sdk = Mock()
        sdk.responses.create.side_effect = lambda **kwargs: events.append("ai") or SimpleNamespace(
            status="completed", output_text="done", output=[], usage=None,
        )
        clients = [AzureClient(ENDPOINT, client=sdk) for _ in range(4)]
        with patch("handwriting_grader.pricing._fetch_page", fetch), ThreadPoolExecutor(4) as pool:
            list(pool.map(lambda i: clients[i % 4].generate_content(
                model="grade-alias" if i % 2 else "ocr-alias", contents="Synthetic",
            ), range(12)))
        self.assertEqual(events[0], "prices")
        fetch.assert_called_once()
        self.assertEqual(sdk.responses.create.call_count, 12)
        self.assertEqual(len(tracker.pricing_verifier.checks), 2)
        self.assertEqual(tracker.rates_table["grade-alias"]["short"]["input"], 2)
        tracker.flush_jsonl(self.root / "telemetry")
        checks = [json.loads(line) for line in (self.root / "telemetry" / "azure_price_checks.jsonl").read_text().splitlines()]
        self.assertEqual(len(checks), 2)
        self.assertEqual(checks[0]["source"]["verification"], "retail")

    def test_new_run_refreshes_even_when_saved_prices_are_current(self):
        path, _ = self.native_config()
        fetch = Mock(return_value={"Items": self.rows})
        for _ in range(2):
            verifier = RunPricingVerifier(path, fetch_page=fetch, now=lambda: NOW)
            verifier.verify(ENDPOINT, "grade-alias")
            verifier.verify(ENDPOINT, "grade-alias")
        self.assertEqual(fetch.call_count, 2)

    def test_direct_python_clients_share_a_run_without_an_active_tracker(self):
        path, _ = self.native_config()
        options = pricing_client_options(path, self.root / "telemetry")
        options["pricing_verifier"]._now = lambda: NOW
        sdk = Mock()
        sdk.responses.create.return_value = SimpleNamespace(
            status="completed", output_text="done", output=[], usage=None,
        )
        with patch("handwriting_grader.pricing._fetch_page", return_value={"Items": self.rows}) as fetch:
            for model in ("grade-alias", "ocr-alias"):
                AzureClient(ENDPOINT, client=sdk, **options).generate_content(model=model, contents="Synthetic")
        fetch.assert_called_once()
        self.assertEqual(len(options["pricing_verifier"].checks), 2)
        self.assertTrue((self.root / "telemetry" / "azure_price_checks.jsonl").is_file())

    def test_creation_and_offline_reports_do_not_refresh_prices(self):
        path, _ = self.native_config()
        verifier, fetch = self.verifier(path)
        AzureClient(ENDPOINT, client=Mock(), pricing_verifier=verifier)
        tracker = TelemetryTracker(self.root / "offline", path)
        with patch("handwriting_grader.pricing._fetch_page", side_effect=AssertionError("Offline")):
            tracker.write_cost_report(self.root / "offline")
            tracker.flush_jsonl(self.root / "offline")
        fetch.assert_not_called()
        self.assertFalse((self.root / "offline" / "azure_price_checks.jsonl").exists())

    def test_missing_configuration_blocks_every_paid_boundary(self):
        sdk = Mock()
        client = AzureClient(ENDPOINT, client=sdk)
        operations = (
            lambda: client.generate_content(model="gpt-6.2-sol", contents="Synthetic"),
            lambda: client.embed_content(model="text-embedding-3-small", contents=["Synthetic"]),
            lambda: client.generate_image(model="gpt-image-2.5-flare", prompt="Synthetic"),
        )
        for operation in operations:
            with self.subTest(operation=operation), self.assertRaises(PriceVerificationError):
                operation()
        self.assertEqual(sdk.mock_calls, [])

    def test_public_image_template_blocks_inference_until_pricing_is_reviewed(self):
        template = Path(__file__).resolve().parents[1] / "image-config.yaml.template"
        config = yaml.safe_load(template.read_text(encoding="utf-8"))
        path = self.root / "image.config.yaml"
        path.write_text(yaml.safe_dump(config))
        verifier, fetch = self.verifier(path)
        sdk = Mock()
        client = AzureClient(config["azure_openai"]["endpoint"], client=sdk, pricing_verifier=verifier)
        with self.assertRaises(PriceVerificationError):
            client.generate_image(model=config["models"]["analytics_image"], prompt="Synthetic")
        self.assertEqual(sdk.mock_calls, [])
        fetch.assert_not_called()

    def test_missing_changed_ambiguous_and_unavailable_prices_block_without_inference(self):
        path, original = self.native_config()
        cases = ("missing", "changed", "ambiguous", "unavailable")
        for case in cases:
            with self.subTest(case=case):
                config = copy.deepcopy(original)
                rows = copy.deepcopy(self.rows)
                if case == "missing":
                    config["pricing"]["grade-alias"]["long"].pop("output")
                elif case == "changed":
                    rows[0]["retailPrice"] = 99
                elif case == "ambiguous":
                    rows.append(meter("6.2-sol ShCo Inp Std Gl", 99, meterId="conflict"))
                path.write_text(yaml.safe_dump(config))
                verifier, fetch = self.verifier(path, rows)
                if case == "unavailable":
                    fetch.side_effect = OSError("offline")
                sdk = Mock()
                client = AzureClient(ENDPOINT, client=sdk, pricing_verifier=verifier)
                for _ in range(2):
                    with self.assertRaises(PriceVerificationError):
                        client.generate_content(model="grade-alias", contents="Synthetic")
                with self.assertRaises(PriceVerificationError):
                    client.generate_content(model="ocr-alias", contents="Synthetic")
                fetch.assert_called_once()
                sdk.responses.create.assert_not_called()

    def test_endpoint_family_profile_and_midrun_edits_cannot_reuse_prices(self):
        path, original = self.native_config()
        for case in ("endpoint", "family", "profile", "currency", "unit"):
            with self.subTest(case=case):
                config = copy.deepcopy(original)
                if case == "endpoint":
                    config["azure_openai"]["endpoint"] = "https://different.openai.azure.com"
                elif case == "family":
                    config["deployment_models"]["grade-alias"] = "gpt-6.1-terra"
                elif case == "profile":
                    config.pop("pricing_lookup")
                    config["pricing_sources"]["grade-alias"].pop("region")
                elif case == "currency":
                    config["pricing_sources"]["grade-alias"]["currency"] = "EUR"
                else:
                    config["pricing_sources"]["grade-alias"]["unit"] = "USD per 1000 tokens"
                path.write_text(yaml.safe_dump(config))
                verifier, fetch = self.verifier(path)
                with self.assertRaises(PriceVerificationError):
                    verifier.verify(ENDPOINT, "grade-alias")
                fetch.assert_not_called()
        path.write_text(yaml.safe_dump(original))
        verifier, fetch = self.verifier(path)
        verifier.verify(ENDPOINT, "grade-alias")
        path.write_text(path.read_text() + "\n# edited during run\n")
        with self.assertRaisesRegex(PriceVerificationError, "changed"):
            verifier.verify(ENDPOINT, "grade-alias")
        fetch.assert_called_once()

    def test_manual_embeddings_need_current_evidence_but_no_retail_adapter(self):
        path, original = self.manual_config("embedding", "text-embedding-3-small")
        verifier, fetch = self.verifier(path)
        sdk = Mock()
        sdk.embeddings.create.return_value = SimpleNamespace(
            data=[SimpleNamespace(index=0, embedding=[1, 0])], usage=None,
        )
        client = AzureClient(ENDPOINT, client=sdk, pricing_verifier=verifier)
        self.assertEqual(client.embed_content(model="manual-alias", contents=["Synthetic"]).embeddings[0].values, [1, 0])
        fetch.assert_not_called()

        for case in ("stale", "future", "wrong-unit", "missing-rate", "undeclared-family"):
            with self.subTest(case=case):
                config = copy.deepcopy(original)
                source = config["pricing_sources"]["manual-alias"]
                if case == "stale":
                    source["verified_at"] = (NOW - timedelta(days=1)).isoformat()
                elif case == "future":
                    source["verified_at"] = (NOW + timedelta(days=1)).isoformat()
                elif case == "wrong-unit":
                    source["unit"] = "USD per 1000 tokens"
                elif case == "missing-rate":
                    config["pricing"]["manual-alias"] = {}
                else:
                    config.pop("deployment_models")
                    source["model"] = "manual-alias"
                path.write_text(yaml.safe_dump(config))
                verifier, fetch = self.verifier(path)
                sdk = Mock()
                with self.assertRaises(PriceVerificationError):
                    AzureClient(ENDPOINT, client=sdk, pricing_verifier=verifier).embed_content(
                        model="manual-alias", contents=["Synthetic"],
                    )
                sdk.embeddings.create.assert_not_called()
                fetch.assert_not_called()

    def test_automatic_embedding_pricing_is_refreshed_and_changed_rates_block_calls(self):
        sku = "text-embedding-3-small-glbl"
        row = meter(sku, 0.00002, productName="Azure OpenAI",
                    meterName=f"{sku} Tokens", unitOfMeasure="1K")
        config = {"azure_openai": {"endpoint": ENDPOINT},
                  "models": {"embedding": "embed"},
                  "deployment_models": {"embed": "text-embedding-3-small"}}
        report = lookup_pricing("eastus", "global-standard", configured_models(config),
                                fetch_page=lambda url: {"Items": [row]}, now=NOW)
        path = self.root / "embedding.yaml"
        write_priced_config(path, config, report)
        verifier, fetch = self.verifier(path, [row])
        self.assertEqual(verifier.verify(ENDPOINT, "embed", kind="embedding")["input"], 0.02)
        fetch.assert_called_once()
        verifier, _ = self.verifier(path, [{**row, "retailPrice": 0.00003}])
        with self.assertRaisesRegex(PriceVerificationError, "differ"):
            verifier.verify(ENDPOINT, "embed", kind="embedding")

    def test_unused_embedding_price_lookup_does_not_block_text(self):
        path, config = self.native_config()
        config["models"]["embedding"] = "embed"
        config["deployment_models"]["embed"] = "text-embedding-3-small"
        path.write_text(yaml.safe_dump(config))

        def fetch(url):
            if "text-embedding" in url:
                raise OSError("embedding retail unavailable")
            return {"Items": self.rows}

        verifier = RunPricingVerifier(path, fetch_page=fetch, now=lambda: NOW)
        self.assertEqual(verifier.verify(ENDPOINT, "grade-alias")["short"]["input"], 2)

    def test_image_price_must_match_request_size_and_quality(self):
        path, config = self.manual_config("analytics_image", "gpt-image-2.5-flare")
        source = config["pricing_sources"]["manual-alias"]
        source.update(unit="USD per million tokens; image USD per generated image",
                      image_size="1536x1024", image_quality="auto")
        path.write_text(yaml.safe_dump(config))
        verifier, fetch = self.verifier(path)
        self.assertEqual(verifier.verify(ENDPOINT, "manual-alias", kind="image", image_size="1536x1024")["image"], 0.1)
        sdk = Mock()
        with self.assertRaises(PriceVerificationError):
            AzureClient(ENDPOINT, client=sdk, pricing_verifier=verifier).generate_image(
                model="manual-alias", prompt="Synthetic", size="1024x1024",
            )
        self.assertEqual(sdk.mock_calls, [])
        fetch.assert_not_called()

    def test_hosted_search_requires_separate_current_tool_fee_evidence(self):
        path, config = self.native_config()
        verifier, fetch = self.verifier(path)
        sdk = Mock()
        client = AzureClient(ENDPOINT, client=sdk, pricing_verifier=verifier)
        with self.assertRaises(PriceVerificationError):
            client.generate_content(model="grade-alias", contents="Synthetic", config=GenerationConfig(tools=["web_search"]))
        sdk.responses.create.assert_not_called()
        config["pricing_tools"] = {"web_search": {"per_1000_calls": 3}}
        config["pricing_tool_sources"] = {"web_search": {
            "model": "web_search", "verification": "manual", "verified_at": NOW.isoformat(),
            "region": "eastus", "deployment_type": "global-standard", "currency": "USD",
            "azure_endpoint": ENDPOINT, "unit": "USD per 1000 calls",
            "source": "https://azure.microsoft.com/en-us/pricing/details/azure-openai/",
        }}
        path.write_text(yaml.safe_dump(config))
        verifier, fetch = self.verifier(path)
        verifier.verify(ENDPOINT, "grade-alias", tools=("web_search",))
        self.assertEqual(verifier.checks[0]["tools"]["web_search"]["rates"]["per_1000_calls"], 3)
        fetch.assert_called_once()
