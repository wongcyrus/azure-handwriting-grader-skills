import tempfile
import unittest
from pathlib import Path

import yaml

from handwriting_grader.discovery import validate_model_eligibility, write_model_config
from handwriting_grader.grading import grading_models
from handwriting_grader.suggestions import load_model_settings


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
            self.assertEqual(load_model_settings(path, "grading"), "gpt-5.4")
            self.assertNotIn("analytics_image", config["models"])
            with self.assertRaises(FileExistsError):
                write_model_config(path, "https://other.openai.azure.com")

    def test_old_google_config_is_not_accepted(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "models.yaml"
            path.write_text("vertex_ai:\n  use_vertexai: true\nmodels:\n  grading: gpt-5.4\n")
            with self.assertRaisesRegex(ValueError, "azure_openai"):
                load_model_settings(path, "grading")
