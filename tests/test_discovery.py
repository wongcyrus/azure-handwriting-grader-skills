import contextlib
import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import yaml

from handwriting_grader.discovery import discover_and_report, validate_model_eligibility, write_model_config
from handwriting_grader.foundry_discovery import discover_foundry, prepare_foundry_config, report_foundry
from handwriting_grader.cli import main
from handwriting_grader.grading import grading_models
from handwriting_grader.suggestions import load_model_settings
from test_pricing import meter, standard_meters


class TestAzureDeploymentConfiguration(unittest.TestCase):
    def test_deployment_aliases_are_allowed_but_google_models_are_rejected(self):
        validate_model_eligibility("school-grader", agent="grading", base_model="gpt-5.4")
        validate_model_eligibility("text-embedding-3-small", agent="embedding")
        validate_model_eligibility("gpt-image-2.5-flare", agent="analytics_image")
        for name in ("gemini-4-argon", "", "my deployment", "https://example.test"):
            with self.subTest(name=name), self.assertRaises(ValueError):
                validate_model_eligibility(name, agent="grading")
        with self.assertRaises(ValueError):
            validate_model_eligibility("text-embedding-3-small", agent="grading")

    def test_text_vision_policy_rejects_old_models_and_undeclared_aliases(self):
        for name in ("gpt-4.1", "GPT-4o", "gpt-3.5-turbo", "o3", "school-grader", "gpt-chat-latest"):
            with self.subTest(name=name), self.assertRaisesRegex(ValueError, "GPT-5"):
                validate_model_eligibility(name, agent="grading")
        for name in ("gpt-5", "gpt-5-mini", "gpt-5.4", "gpt-6.2-sol"):
            with self.subTest(name=name):
                validate_model_eligibility(name, agent="grading")
        for base_model in ("gpt-4.1", "gpt-5.4 invalid", 5):
            with self.subTest(base_model=base_model), self.assertRaisesRegex(ValueError, "GPT-5"):
                validate_model_eligibility("school-grader", agent="grading", base_model=base_model)

    def test_custom_alias_policy_uses_declared_model_without_changing_deployment_name(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "models.yaml"
            config = {"azure_openai": {}, "models": {"grading": "school-chat"},
                      "deployment_models": {"school-chat": "gpt-5.4"}}
            path.write_text(yaml.safe_dump(config))
            self.assertEqual(load_model_settings(path, "grading"), "school-chat")
            config["deployment_models"]["school-chat"] = "gpt-4.1"
            path.write_text(yaml.safe_dump(config))
            with self.assertRaisesRegex(ValueError, "GPT-5"):
                load_model_settings(path, "grading")

    def test_batch_overrides_cannot_bypass_model_policy(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "models.yaml"
            for key in ("batch_grading", "one_pass_grading", "batch_metadata_ocr", "one_pass_metadata_ocr"):
                config = {"azure_openai": {}, "models": {
                    "ocr": "gpt-5.4-mini", "grading": "gpt-5.4", "moderation": "gpt-5.4", key: "gpt-4.1",
                }}
                path.write_text(yaml.safe_dump(config))
                with self.subTest(key=key), self.assertRaisesRegex(ValueError, "GPT-5"):
                    grading_models(path)

    def test_config_template_is_offline_and_never_overwrites(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "models.yaml"
            write_model_config(path, "https://school.openai.azure.com")
            config = yaml.safe_load(path.read_text())
            self.assertEqual(config["azure_openai"]["api_version"], "v1")
            self.assertEqual(load_model_settings(path, "grading"), "gpt-6.1-terra")
            self.assertEqual(load_model_settings(path, "ocr"), "gpt-6-luna")
            self.assertEqual(load_model_settings(path, "moderation"), "gpt-6.2-sol")
            template = yaml.safe_load(
                (Path(__file__).resolve().parents[1] / "model-config.yaml.template").read_text()
            )
            self.assertEqual(config["models"], template["models"])
            self.assertNotIn("analytics_image", config["models"])
            with self.assertRaises(FileExistsError):
                write_model_config(path, "https://other.openai.azure.com")

    def test_discovery_reports_current_candidates_without_network_or_old_recommendations(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output), patch(
            "socket.socket.connect", side_effect=AssertionError("Discovery must remain offline"),
        ):
            result = discover_and_report("https://school.openai.azure.com")
        report = output.getvalue()
        for model in ("gpt-6.1-terra", "gpt-6-luna", "gpt-6.2-sol", "gpt-6.2-astra", "gpt-6.1-sol"):
            self.assertIn(f"| {model} |", report)
        for model in ("gpt-4o", "gpt-4.1", "gpt-5.4", "gpt-chat-latest"):
            self.assertNotIn(f"| {model}", report)
        self.assertIn("documentation snapshot", report)
        self.assertIn("no live verification", report)
        self.assertEqual(result["azure_openai"]["endpoint"], "https://school.openai.azure.com")

    def test_old_google_config_is_not_accepted(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "models.yaml"
            path.write_text("vertex_ai:\n  use_vertexai: true\nmodels:\n  grading: gpt-5.4\n")
            with self.assertRaisesRegex(ValueError, "azure_openai"):
                load_model_settings(path, "grading")


class TestFoundryDiscovery(unittest.TestCase):
    account_id = ("/subscriptions/12345678-1234-1234-1234-123456789012/resourceGroups/school"
                  "/providers/Microsoft.CognitiveServices/accounts/foundry")

    def account(self):
        return {"id": self.account_id, "name": "foundry", "location": "eastus",
                "properties": {"endpoint": "https://school.cognitiveservices.azure.com",
                               "endpoints": {"OpenAI Language Model Instance API":
                                             "https://school.openai.azure.com/"}}}

    def deployments(self):
        def deployment(name, family):
            return {"name": name, "sku": {"name": "GlobalStandard"}, "properties": {
                "provisioningState": "Succeeded",
                "model": {"format": "OpenAI", "name": family,
                          "version": "2026-11-17" if family == "gpt-6.2-sol" else "1"}}}
        return [deployment("grade", "gpt-6.2-sol"), deployment("embed", "text-embedding-3-small")]

    def test_account_name_and_project_id_resolve_without_inference(self):
        def fetch(url, credential):
            if "/subscriptions?" in url:
                return {"value": [{"subscriptionId": "12345678-1234-1234-1234-123456789012"}]}
            if "/accounts?" in url:
                return {"value": [self.account()]}
            if "/deployments?" in url:
                return {"value": self.deployments()}
            return self.account()
        for resource in ("foundry", self.account_id + "/projects/my-project"):
            result = discover_foundry(resource, credential=object(), fetch_page=fetch)
            self.assertEqual(result["resource_id"], self.account_id)
            self.assertEqual(result["endpoint"], "https://school.openai.azure.com")
            self.assertEqual(result["deployments"], self.deployments())

    def test_cli_passes_selection_without_an_inference_call(self):
        with patch("handwriting_grader.foundry_discovery.report_foundry") as report:
            self.assertEqual(main(["discover-foundry", "--resource", "foundry",
                                   "--text-deployment", "grade"]), 0)
        report.assert_called_once_with("foundry", text_deployment="grade", embedding_deployment=None,
                                       image_deployment=None, meter_region=None, write_config=None)

    def test_pagination_must_not_send_credentials_to_untrusted_hosts(self):
        fetch = lambda url, credential: {"value": [], "nextLink": "https://example.test/next"}
        with self.assertRaisesRegex(ValueError, "pagination"):
            discover_foundry("foundry", credential=object(), fetch_page=fetch)

    def test_config_uses_discovered_models_and_prices_and_refuses_overwrite(self):
        sku = "text-embedding-3-small-glbl"
        row = meter(sku, 0.00002, productName="Azure OpenAI",
                    meterName=f"{sku} Tokens", unitOfMeasure="1K")
        foundry = {**self.account(), "resource_id": self.account_id, "endpoint": "https://school.openai.azure.com",
                   "region": "eastus", "deployments": self.deployments()}
        with tempfile.TemporaryDirectory() as temp, \
                patch("handwriting_grader.foundry_discovery.discover_foundry", return_value=foundry), \
                patch("handwriting_grader.pricing._fetch_page",
                      side_effect=lambda url: {"Items": [row] if sku in url else standard_meters()}), \
                contextlib.redirect_stdout(io.StringIO()):
            target = Path(temp) / "foundry.yaml"
            config = report_foundry("foundry", write_config=target)
            self.assertEqual(config["models"]["grading"], "grade")
            self.assertEqual(config["models"]["embedding"], "embed")
            self.assertEqual(config["pricing"]["embed"]["input"], 0.02)
            self.assertEqual(yaml.safe_load(target.read_text()), config)
            with self.assertRaises(FileExistsError):
                report_foundry("foundry", write_config=target)

    def test_multiple_candidates_require_selection(self):
        deployments = self.deployments()
        deployments.append({**deployments[0], "name": "another"})
        foundry = {"endpoint": "https://school.openai.azure.com", "region": "eastus", "deployments": deployments}
        with self.assertRaisesRegex(ValueError, "--text-deployment"):
            prepare_foundry_config(foundry)

    def test_preview_reports_multiple_text_candidates_without_requiring_selection(self):
        deployments = self.deployments()
        deployments.append({**deployments[0], "name": "another"})
        foundry = {**self.account(), "resource_id": self.account_id, "endpoint": "https://school.openai.azure.com",
                   "region": "eastus", "deployments": deployments}
        sku = "text-embedding-3-small-glbl"
        row = meter(sku, 0.00002, productName="Azure OpenAI",
                    meterName=f"{sku} Tokens", unitOfMeasure="1K")
        output = io.StringIO()
        with patch("handwriting_grader.foundry_discovery.discover_foundry", return_value=foundry), \
                patch("handwriting_grader.pricing._fetch_page",
                      side_effect=lambda url: {"Items": [row] if sku in url else standard_meters()}), \
                contextlib.redirect_stdout(output):
            config = report_foundry("foundry")
        self.assertIn("Multiple grading deployments", output.getvalue())
        self.assertNotIn("grading", config["models"])
        self.assertEqual(config["models"]["embedding"], "embed")

    def test_optional_ambiguity_is_skipped_and_model_version_mismatch_is_unpriced(self):
        deployments = self.deployments()
        deployments[0]["properties"]["model"]["version"] = "unrecognized"
        deployments.append({**deployments[1], "name": "another-embedding"})
        foundry = {"endpoint": "https://school.openai.azure.com", "region": "eastus", "deployments": deployments}
        with patch("handwriting_grader.pricing._fetch_page", return_value={"Items": standard_meters()}), \
                contextlib.redirect_stdout(io.StringIO()):
            config = prepare_foundry_config(foundry)
        self.assertNotIn("embedding", config["models"])
        self.assertEqual(config["pricing"]["grade"], {})

    def test_alternate_global_meter_is_previewed_but_not_silently_selected(self):
        sku = "text-embedding-3-small-glbl"
        row = meter(sku, 0.00002, productName="Azure OpenAI",
                    meterName=f"{sku} Tokens", unitOfMeasure="1K")
        foundry = {**self.account(), "resource_id": self.account_id, "endpoint": "https://school.openai.azure.com",
                   "region": "eastasia", "deployments": [self.deployments()[1]]}
        output = io.StringIO()
        with patch("handwriting_grader.foundry_discovery.discover_foundry", return_value=foundry), \
                patch("handwriting_grader.pricing._fetch_page",
                      side_effect=lambda url: {"Items": [row] if "eastus" in url else []}), \
                contextlib.redirect_stdout(output):
            config = report_foundry("foundry")
        self.assertIn("Alternative eastus retail profile: 0.02", output.getvalue())
        self.assertEqual(config["pricing"]["embed"], {})
        self.assertEqual(config["pricing_sources"]["embed"]["region"], "eastasia")
