import tempfile
import unittest
from pathlib import Path

import yaml

from handwriting_grader.discovery import validate_model_eligibility, write_model_config
from handwriting_grader.suggestions import load_model_settings


class TestAzureDeploymentConfiguration(unittest.TestCase):
    def test_deployment_aliases_are_allowed_but_google_models_are_rejected(self):
        validate_model_eligibility("school-grader", agent="grading")
        validate_model_eligibility("text-embedding-3-small", agent="embedding")
        for name in ("gemini-4-argon", "", "my deployment", "https://example.test"):
            with self.subTest(name=name), self.assertRaises(ValueError):
                validate_model_eligibility(name, agent="grading")
        with self.assertRaises(ValueError):
            validate_model_eligibility("text-embedding-3-small", agent="grading")

    def test_config_template_is_offline_and_never_overwrites(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "models.yaml"
            write_model_config(path, "https://school.openai.azure.com")
            config = yaml.safe_load(path.read_text())
            self.assertEqual(config["azure_openai"]["api_version"], "v1")
            self.assertEqual(load_model_settings(path, "grading"), "gpt-4.1")
            self.assertNotIn("analytics_image", config["models"])
            with self.assertRaises(FileExistsError):
                write_model_config(path, "https://other.openai.azure.com")

    def test_old_google_config_is_not_accepted(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "models.yaml"
            path.write_text("vertex_ai:\n  use_vertexai: true\nmodels:\n  grading: gpt-4.1\n")
            with self.assertRaisesRegex(ValueError, "azure_openai"):
                load_model_settings(path, "grading")
