import io
import json
import shutil
import threading
import unittest
import uuid
import yaml
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from docx import Document
from openpyxl import load_workbook
from PIL import Image
from pptx import Presentation

from handwriting_grader import advanced, score_editor, verification
from handwriting_grader.azure_ai import Usage
from handwriting_grader.cli import main
from handwriting_grader.regions import file_hash
from handwriting_grader.telemetry import get_active_tracker


ENDPOINT = "https://example.openai.azure.com"


class AzureAuxiliaryTests(unittest.TestCase):
    def setUp(self):
        self.root = Path.cwd() / f".azure-auxiliary-test-{uuid.uuid4().hex}"
        self.root.mkdir()
        self.addCleanup(shutil.rmtree, self.root)

    def test_verification_uses_web_search_and_filters_returned_sources(self):
        rubric = self.root / "rubric.xlsx"
        rubric.write_bytes(b"rubric fixture")
        model_config = self.root / "models.yaml"
        model_config.write_text("models: {}\n", encoding="utf-8")
        response = SimpleNamespace(
            text="Check this reviewed factual claim.", usage_metadata=None,
            sources=[
                {"title": "Evidence", "url": "https://example.org/evidence"},
                {"title": "Other evidence", "url": "http://example.org/other"},
                {"title": "Unsafe", "url": "javascript:alert(1)"},
                {"title": "Local", "url": "file:///etc/passwd"},
                {"title": "Missing host", "url": "https:///invalid"},
                {"title": "Credentials", "url": "https://name:secret@example.org"},
                {"title": "Whitespace", "url": "https://example.org/\ninvalid"},
            ],
        )
        client = Mock()
        client.__enter__ = Mock(return_value=client)
        client.__exit__ = Mock(return_value=False)
        client.generate_content.return_value = response
        with patch.object(verification, "verify_rubric_source", return_value=(self.root, {})), \
                patch.object(verification, "read_rubric", return_value=[{"question_number": "Q1"}]), \
                patch.object(verification, "load_model_settings", return_value="search-deployment"), \
                patch.object(verification, "get_thinking_config", return_value=None), \
                patch.object(verification, "AzureClient", return_value=client) as factory:
            target = verification.verify_rubric({}, self.root, rubric, model_config, ENDPOINT, "v1")
        factory.assert_called_once_with(endpoint=ENDPOINT, api_version="v1", pricing_config=model_config)
        self.assertEqual(client.generate_content.call_args.kwargs["config"].tools, ["web_search"])
        book = load_workbook(target / "verification.xlsx")
        self.addCleanup(book.close)
        sources = book.active.cell(2, 3).value
        self.assertEqual(sources, "Evidence: https://example.org/evidence\nOther evidence: http://example.org/other")
        manifest = json.loads((target / "manifest.json").read_text())
        self.assertEqual(manifest["endpoint"], ENDPOINT)
        self.assertEqual(manifest["api_version"], "v1")
        self.assertNotIn("project", manifest)

    def test_unsupported_search_propagates_without_fabricated_report(self):
        (self.root / "rubric.xlsx").write_bytes(b"rubric")
        model_config = self.root / "models.yaml"
        model_config.write_text("models: {}\n")
        client = Mock()
        client.__enter__ = Mock(return_value=client)
        client.__exit__ = Mock(return_value=False)
        client.generate_content.side_effect = ValueError("web_search unsupported")
        with patch.object(verification, "verify_rubric_source", return_value=(self.root, {})), \
                patch.object(verification, "read_rubric", return_value=[{"question_number": "Q1"}]), \
                patch.object(verification, "load_model_settings", return_value="search-alias"), \
                patch.object(verification, "get_thinking_config", return_value=None), \
                patch.object(verification, "AzureClient", return_value=client):
            with self.assertRaisesRegex(ValueError, "unsupported"):
                verification.verify_rubric({}, self.root, None, model_config, ENDPOINT, "v1")
        self.assertFalse((self.root / "verification" / "manifest.json").exists())
        self.assertFalse((self.root / "verification" / "verification.docx").exists())

    def test_infographic_transport_and_cached_image(self):
        client = Mock()
        client.generate_image.return_value = SimpleNamespace(image_bytes=b"PNG", usage_metadata=None)
        target = self.root / "infographics" / "class.png"
        with patch.object(advanced, "get_active_tracker", return_value=None):
            result, error = advanced._generate_infographic(client, "image-alias", "Draw a diagram", target)
            self.assertEqual((result, error), (target, None))
            advanced._generate_infographic(client, "image-alias", "Draw a diagram", target)
        client.generate_image.assert_called_once_with(
            model="image-alias", prompt="Draw a diagram", size="1536x1024"
        )
        self.assertEqual(target.read_bytes(), b"PNG")

    def _report_fixture(self):
        model_config = self.root / "models.yaml"
        model_config.write_text("models:\n  analytics_image: image-alias\n")
        (self.root / "review.xlsx").write_bytes(b"reviewed workbook")
        (self.root / "manifest.json").write_text(json.dumps({
            "model_config_path": str(model_config),
            "model_config_sha256": file_hash(model_config),
            "endpoint": ENDPOINT, "api_version": "v1",
        }))
        approval = {
            "review_sha256": file_hash(self.root / "review.xlsx"),
            "manifest_sha256": file_hash(self.root / "manifest.json"),
        }
        (self.root / "approval.json").write_text(json.dumps(approval))
        questions = [{"question_number": "Q1", "marks": 2}]
        validated = (None, None, None, questions)
        reviewed = (self.root, validated, {0: "Human-reviewed student feedback"},
                    {"q1": "Human-reviewed question analysis"}, "Human-reviewed class analysis", approval)
        # Use the canonical question-key normalizer rather than assuming case normalization.
        reviewed[3].clear()
        reviewed[3][advanced.question_key("Q1")] = "Human-reviewed question analysis"
        rows = [{"script_index": 0, "id": "001", "marks": [1], "total": 1}]
        return model_config, reviewed, rows

    def test_advanced_report_is_offline_by_default_and_keeps_reviewed_text(self):
        _, reviewed, rows = self._report_fixture()
        with patch.object(advanced, "read_approved_analysis", return_value=reviewed), \
                patch.object(advanced, "validate_analysis"), \
                patch.object(advanced, "report_rows", return_value=(rows, {})), \
                patch.object(advanced, "AzureClient", side_effect=AssertionError("Must remain offline")):
            target = advanced.create_advanced_report({}, self.root, None)
        text = "\n".join(p.text for p in Document(target / "teacher-report.docx").paragraphs)
        for expected in ("Human-reviewed student feedback", "Human-reviewed question analysis",
                         "Human-reviewed class analysis"):
            self.assertIn(expected, text)
        self.assertTrue((target / "class-presentation.pptx").is_file())

    def test_infographics_require_current_config_and_configured_deployment(self):
        model_config, reviewed, _ = self._report_fixture()
        model_config.write_text("models: {}\n")
        with patch.object(advanced, "read_approved_analysis", return_value=reviewed), \
                patch.object(advanced, "AzureClient") as factory:
            with self.assertRaisesRegex(ValueError, "configuration changed"):
                advanced.create_advanced_report({}, self.root, None, infographics=True)
            factory.assert_not_called()
        manifest_path = self.root / "manifest.json"
        manifest = json.loads(manifest_path.read_text())
        manifest["model_config_sha256"] = file_hash(model_config)
        manifest_path.write_text(json.dumps(manifest))
        with patch.object(advanced, "read_approved_analysis", return_value=reviewed), \
                patch.object(advanced, "load_model_settings", side_effect=ValueError("Image deployment required")), \
                patch.object(advanced, "AzureClient") as factory:
            with self.assertRaisesRegex(ValueError, "deployment required"):
                advanced.create_advanced_report({}, self.root, None, infographics=True, image_model="override")
            factory.assert_not_called()
        self.assertFalse((self.root / "reports").exists())

    def test_requested_infographics_use_configured_azure_transport_without_retries(self):
        model_config, reviewed, rows = self._report_fixture()
        image = io.BytesIO()
        Image.new("RGB", (16, 9), "white").save(image, format="PNG")
        client = Mock()
        client.__enter__ = Mock(return_value=client)
        client.__exit__ = Mock(return_value=False)
        client.generate_image.return_value = SimpleNamespace(image_bytes=image.getvalue(), usage_metadata=None)
        with patch.object(advanced, "read_approved_analysis", return_value=reviewed), \
                patch.object(advanced, "validate_analysis"), \
                patch.object(advanced, "report_rows", return_value=(rows, {})), \
                patch.object(advanced, "load_model_settings", return_value="image-alias"), \
                patch.object(advanced, "AzureClient", return_value=client) as factory, \
                patch.object(advanced.time, "sleep"):
            target = advanced.create_advanced_report({}, self.root, None, infographics=True)
        factory.assert_called_once_with(
            endpoint=ENDPOINT, api_version="v1", max_retries=0, pricing_config=model_config,
        )
        self.assertEqual(client.generate_image.call_count, 2)
        self.assertEqual(json.loads((target / "manifest.json").read_text())["infographics_count"], 2)
        slides = Presentation(target / "class-presentation.pptx").slides
        self.assertEqual(len(slides), 5)
        slide_text = [" ".join(s.text for s in slide.shapes if s.has_text_frame) for slide in slides]
        self.assertIn("Human-reviewed class analysis", slide_text[0])
        self.assertIn("mean 1.00 / 2", slide_text[0])
        self.assertIn("Human-reviewed question analysis", slide_text[3])
        self.assertIn("mean 1.00 / 2 (50.0%)", slide_text[3])
        for index in (1, 4):
            self.assertIn("may be inaccurate or sample-based", slide_text[index])
            self.assertEqual(sum(shape.shape_type == 13 for shape in slides[index].shapes), 1)

    def test_failed_infographic_keeps_editable_slide_without_image_slide(self):
        _, reviewed, rows = self._report_fixture()
        image = io.BytesIO()
        Image.new("RGB", (16, 9), "white").save(image, format="PNG")
        client = Mock()
        client.__enter__ = Mock(return_value=client)
        client.__exit__ = Mock(return_value=False)
        client.generate_image.side_effect = [
            SimpleNamespace(image_bytes=image.getvalue(), usage_metadata=None),
            ValueError("generation failed"),
        ]
        with patch.object(advanced, "read_approved_analysis", return_value=reviewed), \
                patch.object(advanced, "validate_analysis"), \
                patch.object(advanced, "report_rows", return_value=(rows, {})), \
                patch.object(advanced, "load_model_settings", return_value="image-alias"), \
                patch.object(advanced, "AzureClient", return_value=client), \
                patch.object(advanced.time, "sleep"):
            target = advanced.create_advanced_report({}, self.root, None, infographics=True)
        slides = Presentation(target / "class-presentation.pptx").slides
        self.assertEqual(len(slides), 4)
        self.assertIn("Human-reviewed question analysis",
                      " ".join(s.text for s in slides[-1].shapes if s.has_text_frame))
        manifest = json.loads((target / "manifest.json").read_text())
        self.assertEqual(manifest["infographics_count"], 1)
        self.assertEqual(manifest["failed_infographics"][0]["key"], "q_0")

    def test_separate_image_resource_preserves_analysis_and_existing_reports(self):
        _, reviewed, rows = self._report_fixture()
        image_config = self.root / "image.config.yaml"
        image_endpoint = "https://images.services.ai.azure.com"
        template = Path(__file__).resolve().parents[1] / "image-config.yaml.template"
        image_settings = yaml.safe_load(template.read_text(encoding="utf-8"))
        image_settings["azure_openai"]["endpoint"] = image_endpoint
        image_settings["deployment_models"]["school-image"] = "gpt-image-2.5-sunburst"
        image_config.write_text(yaml.safe_dump(image_settings))
        original_hashes = {name: file_hash(self.root / name)
                           for name in ("models.yaml", "manifest.json", "review.xlsx", "approval.json")}
        previous_report = self.root / "reports"
        previous_report.mkdir()
        (previous_report / "teacher-report.docx").write_bytes(b"original report")
        old_cache = self.root / "infographics"
        old_cache.mkdir()
        (old_cache / "class.png").write_bytes(b"another resource's image")
        image = io.BytesIO()
        Image.new("RGB", (16, 9), "white").save(image, format="PNG")
        client = Mock()
        client.__enter__ = Mock(return_value=client)
        client.__exit__ = Mock(return_value=False)
        client.generate_image.return_value = SimpleNamespace(image_bytes=image.getvalue(), usage_metadata=None)
        with patch.object(advanced, "read_approved_analysis", return_value=reviewed), \
                patch.object(advanced, "validate_analysis"), \
                patch.object(advanced, "report_rows", return_value=(rows, {})), \
                patch.object(advanced, "AzureClient", return_value=client) as factory, \
                patch.object(advanced.time, "sleep"):
            target = advanced.create_advanced_report(
                {}, self.root, None, infographics=True,
                image_model_config=image_config, report_name="reports-infographics",
            )
        factory.assert_called_once_with(
            endpoint=image_endpoint, api_version="v1", max_retries=0, pricing_config=image_config,
        )
        self.assertEqual(client.generate_image.call_count, 2)
        self.assertEqual(target, self.root / "reports-infographics")
        self.assertTrue((target / "infographics" / "class.png").is_file())
        self.assertEqual((previous_report / "teacher-report.docx").read_bytes(), b"original report")
        for name, digest in original_hashes.items():
            self.assertEqual(file_hash(self.root / name), digest)
        manifest = json.loads((target / "manifest.json").read_text())
        self.assertEqual(manifest["image_generation"]["endpoint"], image_endpoint)
        self.assertEqual(manifest["image_generation"]["model_config_sha256"], file_hash(image_config))

    def test_separate_image_resource_rejects_project_url_and_missing_api_version(self):
        _, reviewed, _ = self._report_fixture()
        image_config = self.root / "image.config.yaml"
        for azure in (
            {"endpoint": "https://images.services.ai.azure.com/api/projects/project", "api_version": "v1"},
            {"endpoint": "https://images.services.ai.azure.com"},
        ):
            image_config.write_text(yaml.safe_dump({
                "azure_openai": azure, "models": {"analytics_image": "gpt-image-2.5-sunburst"},
            }))
            with self.subTest(azure=azure), \
                    patch.object(advanced, "read_approved_analysis", return_value=reviewed), \
                    patch.object(advanced, "AzureClient") as factory:
                with self.assertRaises(ValueError):
                    advanced.create_advanced_report(
                        {}, self.root, None, infographics=True, image_model_config=image_config,
                    )
                factory.assert_not_called()
            self.assertFalse((self.root / "reports").exists())

    def test_named_report_cannot_escape_analysis_directory(self):
        _, reviewed, _ = self._report_fixture()
        for name in ("../outside", "/outside", ".", "nested/reports"):
            with self.subTest(name=name), \
                    patch.object(advanced, "read_approved_analysis", return_value=reviewed):
                with self.assertRaisesRegex(ValueError, "single ASCII folder"):
                    advanced.create_advanced_report({}, self.root, None, report_name=name)

    def test_infographic_cli_prices_calls_using_separate_image_configuration(self):
        _, _, _ = self._report_fixture()
        image_config = self.root / "image.config.yaml"
        image_config.write_text("pricing:\n  image-alias:\n    input: 5\n    output: 30\n")
        analysis = self.root / "ai-analysis"
        analysis.mkdir()

        def report(*args, **kwargs):
            self.assertEqual(kwargs["image_model_config"], image_config)
            self.assertEqual(kwargs["report_name"], "reports-infographics")
            get_active_tracker().record_call(
                "infographics", "Class", "image-alias", Usage(1000, 1000, 2000), 1,
            )
            return analysis / "reports-infographics"

        with patch("handwriting_grader.cli.load_config", return_value={"exam": {"output_dir": "output"}}), \
                patch("handwriting_grader.cli.check_exam", return_value=([], {})), \
                patch("handwriting_grader.run_context.run_directory", return_value=self.root), \
                patch.object(advanced, "create_advanced_report", side_effect=report):
            self.assertEqual(main([
                "advanced-report", "--exam", str(self.root / "exam.yaml"), "--infographics", "--confirm-cost",
                "--image-model-config", str(image_config), "--report-name", "reports-infographics",
            ]), 0)
        trace = json.loads((analysis / "telemetry" / "azure_usage.jsonl").read_text())
        self.assertTrue(trace["cost_known"])
        self.assertAlmostEqual(trace["cost_usd"], 0.035)

    def test_infographic_cli_uses_pricing_from_analysis_manifest(self):
        model_config, _, _ = self._report_fixture()
        model_config.write_text("pricing:\n  image-alias:\n    input: 2\n    output: 8\n")
        analysis = self.root / "ai-analysis"
        analysis.mkdir()
        (self.root / "manifest.json").rename(analysis / "manifest.json")

        def report(*args, **kwargs):
            get_active_tracker().record_call(
                "infographics", "Class", "image-alias", Usage(1000, 1000, 2000), 1,
            )
            return analysis / "reports"

        with patch("handwriting_grader.cli.load_config", return_value={"exam": {"output_dir": "output"}}), \
                patch("handwriting_grader.cli.check_exam", return_value=([], {})), \
                patch("handwriting_grader.run_context.run_directory", return_value=self.root), \
                patch.object(advanced, "create_advanced_report", side_effect=report):
            self.assertEqual(main([
                "advanced-report", "--exam", str(self.root / "exam.yaml"), "--infographics", "--confirm-cost",
            ]), 0)
        trace = json.loads((analysis / "telemetry" / "azure_usage.jsonl").read_text())
        self.assertTrue(trace["cost_known"])
        self.assertEqual(trace["cost_usd"], 0.01)
        self.assertEqual(json.loads((analysis / "cost_summary.json").read_text())["total_cost_usd"], 0.01)

    def test_retry_cli_prices_calls_in_the_selected_child_run(self):
        model_config = self.root / "models.yaml"
        model_config.write_text("pricing:\n  school-chat:\n    input: 2\n    output: 8\n")
        target = self.root / "output" / "runs" / "child" / "grading"
        info = {
            "target": target, "failed_marks": [{}], "unmoderated_questions": [],
            "regions_updated": False, "target_question": None, "estimated_requests": 1,
            "manifest": {"endpoint": ENDPOINT, "api_version": "v1", "models": {"grading": "school-chat"},
                         "model_config_path": str(model_config)},
        }

        def retry(*args, **kwargs):
            get_active_tracker().record_call(
                "grading", "Q1", "school-chat", Usage(1000, 1000, 2000), 1,
            )
            return target

        with patch("handwriting_grader.cli.load_config", return_value={"exam": {"output_dir": "output"}}), \
                patch("handwriting_grader.cli.check_exam", return_value=([], {})), \
                patch("handwriting_grader.grading.inspect_retry_grading", return_value=info), \
                patch("handwriting_grader.grading.retry_grading", side_effect=retry):
            self.assertEqual(main([
                "retry-grading", "--exam", str(self.root / "exam.yaml"), "--run", "child", "--confirm-cost",
            ]), 0)
        trace = json.loads((target / "telemetry" / "azure_usage.jsonl").read_text())
        self.assertTrue(trace["cost_known"])
        self.assertEqual(trace["cost_usd"], 0.01)
        self.assertEqual(json.loads((target / "cost_summary.json").read_text())["total_cost_usd"], 0.01)
        self.assertFalse((self.root / "output" / "grading" / "telemetry").exists())

    def test_editor_initialization_does_not_load_ai_even_with_consent(self):
        questions = [{"question_number": "Q1"}]
        config = {"exam": {"model_config": "does-not-exist.yaml"}, "layout": {"pages_per_student": 1}}
        for allow_ai in (False, True):
            with self.subTest(allow_ai=allow_ai), \
                    patch.object(score_editor, "verify_grading_run", return_value=(self.root, {}, {}, questions)), \
                    patch.object(score_editor, "approved_inputs", return_value=(None, None, None, {})), \
                    patch.object(score_editor, "present_roster", return_value=[]), \
                    patch.object(score_editor, "load_state"), \
                    patch.object(score_editor.ThreadingHTTPServer, "__init__", return_value=None), \
                    patch.object(score_editor.ScoreServer, "get_embedding_client", side_effect=AssertionError("Not lazy")):
                server = score_editor.ScoreServer(config, self.root, allow_ai=allow_ai)
            self.assertIsNone(server._azure_client)

    def _editor(self, allow_ai=False):
        server = object.__new__(score_editor.ScoreServer)
        server.allow_ai = allow_ai
        server._azure_client = None
        server._embedding_model = None
        server.embedding_tracker = None
        server.expected_revision = None
        server.embedding_model_name = "none"
        server.embedding_namespace = ""
        server.embedding_model_config = self.root / "models.yaml"
        server.embedding_cache_enabled = False
        server.shared_cache_path = None
        server.embedding_cache = {}
        server.embedding_lock = threading.Lock()
        server.lock = threading.Lock()
        server.precomputed_clusters = {}
        server.config_dir = self.root
        server.config = {"exam": {"model_config": "models.yaml"}}
        server.root = self.root
        return server

    def test_offline_clustering_normalizes_answers_without_azure(self):
        server = self._editor()
        marks = {(0, "Q1"): {"answer": "Same answer"}, (1, "Q1"): {"answer": "  SAME   answer "},
                 (2, "Q1"): {"answer": "Different"}}
        key = score_editor.question_key("Q1")
        marks = {(idx, key): value for (idx, _), value in marks.items()}
        state = (self.root, "", [], [{"question_number": "Q1"}], {0: {}, 1: {}, 2: {}}, marks)
        with patch.object(score_editor, "load_state", return_value=state), \
                patch("handwriting_grader.azure_ai.AzureClient", side_effect=AssertionError("Paid call")):
            result = server.cluster_question(0)
        self.assertEqual(len(result["clusters"]), 2)
        self.assertEqual(len(result["clusters"][0]["scripts"]), 2)
        self.assertEqual(result["model"], "none")
        self.assertEqual(result["method"], "exact")

    def test_offline_cluster_file_does_not_enable_embedding_label(self):
        (self.root / "clusters.json").write_text(json.dumps({
            "Q1": {"model": "none", "method": "exact", "answer_hash": "hash"}
        }))
        config = {"exam": {}, "layout": {"pages_per_student": 1}}
        with patch.object(score_editor, "verify_grading_run", return_value=(self.root, {}, {}, [])), \
                patch.object(score_editor, "approved_inputs", return_value=(None, None, None, {})), \
                patch.object(score_editor, "present_roster", return_value=[]), \
                patch.object(score_editor, "load_state"), \
                patch.object(score_editor.ThreadingHTTPServer, "__init__", return_value=None):
            server = score_editor.ScoreServer(config, self.root)
        self.assertFalse(server.has_clusters)

    def test_shared_embedding_cache_requires_explicit_opt_in(self):
        from handwriting_grader.cache import shared_embedding_cache_path

        model_config = self.root / "models.yaml"
        for content in ("{}", "caching:\n  enabled: true\n  scope: run\n",
                        "caching:\n  enabled: false\n  scope: shared\n  directory: private\n"):
            model_config.write_text(content)
            self.assertIsNone(shared_embedding_cache_path(model_config, "model", namespace=ENDPOINT))
        model_config.write_text("caching:\n  enabled: true\n  scope: shared\n  directory: private\n")
        self.assertEqual(shared_embedding_cache_path(model_config, "model", namespace=ENDPOINT).parent,
                         self.root / "private" / "embeddings")
        model_config.write_text("caching:\n  enabled: true\n  scope: shared\n")
        with self.assertRaisesRegex(ValueError, "caching.directory"):
            shared_embedding_cache_path(model_config, "model", namespace=ENDPOINT)

    def test_saved_clusters_do_not_override_consent_threshold_or_answers(self):
        server = self._editor()
        key = score_editor.question_key("Q1")
        marks = {(0, key): {"answer": "First"}, (1, key): {"answer": "Second"}}
        state = (self.root, "", [], [{"question_number": "Q1"}], {0: {}, 1: {}}, marks)
        with patch.object(score_editor, "load_state", return_value=state):
            offline = server.cluster_question(0)
        self.assertEqual(len(offline["clusters"]), 2)
        server.precomputed_clusters = {"Q1": offline}
        server.allow_ai = True
        server.embedding_namespace = ENDPOINT
        server.shared_cache_path = self.root / "shared.json"
        fake = Mock()
        fake.embed_content.return_value = SimpleNamespace(embeddings=[SimpleNamespace(values=[1, 0])])
        with patch.object(score_editor, "load_state", return_value=state), \
                patch.object(server, "get_embedding_client", return_value=(fake, "embedding-alias")):
            paid = server.cluster_question(0)
        self.assertEqual(fake.embed_content.call_count, 2)
        self.assertEqual(len(paid["clusters"]), 1)
        server.precomputed_clusters = {"Q1": paid}
        server.allow_ai = False
        server.embedding_cache["second"] = [0.9, 0.44]
        with patch.object(score_editor, "load_state", return_value=state):
            self.assertEqual(len(server.cluster_question(0, threshold=0.95)["clusters"]), 2)
            marks[(1, key)]["answer"] = ""
            clusters = server.cluster_question(0)["clusters"]
        self.assertTrue(any(cluster["rep_text"] == "(empty)" for cluster in clusters))
        self.assertEqual(fake.embed_content.call_count, 2)

    def test_semantic_results_survive_without_cache_but_not_answer_changes(self):
        server = self._editor(allow_ai=True)
        key = score_editor.question_key("Q1")
        marks = {(0, key): {"answer": "First"}, (1, key): {"answer": "Second"}}
        state = (self.root, "revision", [], [{"question_number": "Q1"}], {0: {}, 1: {}}, marks)
        fake = Mock()
        fake.embed_content.return_value = SimpleNamespace(embeddings=[SimpleNamespace(values=[1, 0])])
        with patch.object(score_editor, "load_state", return_value=state), \
                patch.object(server, "get_embedding_client", return_value=(fake, "embedding-alias")):
            paid = server.cluster_question(0)
        self.assertEqual(paid["method"], "embedding")
        self.assertFalse((self.root / ".embedding_cache.json").exists())
        server.allow_ai = False
        server.embedding_cache.clear()
        server.precomputed_clusters = {"Q1": paid}
        with patch.object(score_editor, "load_state", return_value=state):
            self.assertEqual(server.cluster_question(0), paid)
            marks[(1, key)]["answer"] = "Changed"
            self.assertEqual(server.cluster_question(0)["method"], "exact")
        self.assertEqual(fake.embed_content.call_count, 2)

    def test_embedding_client_requires_consent_and_namespaces_endpoint_and_deployment(self):
        server = self._editor()
        with patch("handwriting_grader.azure_ai.AzureClient", side_effect=AssertionError("No consent")):
            self.assertEqual(server.get_embedding_client(), (None, "none"))
        model_config = self.root / "models.yaml"
        model_config.write_text(f"azure_openai:\n  endpoint: {ENDPOINT}/\nmodels:\n  embedding: embedding-alias\n")
        server.allow_ai = True
        server.embedding_cache = {"old": [1, 0]}
        server.embedding_namespace = "https://different.openai.azure.com"
        server.embedding_model_name = "embedding-alias"
        fake = Mock()
        with patch("handwriting_grader.azure_ai.AzureClient", return_value=fake) as factory, \
                patch("handwriting_grader.suggestions.load_model_settings", return_value="embedding-alias"), \
                patch.object(score_editor, "shared_embedding_cache_path", return_value=self.root / "shared.json") as cache:
            self.assertEqual(server.get_embedding_client(), (fake, "embedding-alias"))
        self.assertEqual(server.embedding_cache, {})
        cache.assert_called_once_with(model_config, "embedding-alias", namespace=ENDPOINT)
        factory.assert_called_once_with(
            endpoint=ENDPOINT + "/", api_version="v1", pricing_verifier=unittest.mock.ANY,
        )
        with patch.object(score_editor.ThreadingHTTPServer, "server_close"):
            server.server_close()
        fake.close.assert_called_once()

    def test_cached_vectors_cluster_offline_and_consent_allows_missing_embeddings(self):
        key = score_editor.question_key("Q1")
        state = (self.root, "", [], [{"question_number": "Q1"}], {0: {}, 1: {}},
                 {(0, key): {"answer": "First"}, (1, key): {"answer": "Second"}})
        server = self._editor()
        server.embedding_cache = {"first": [1, 0], "second": [1, 0]}
        server.embedding_model_name = "cached-deployment"
        with patch.object(score_editor, "load_state", return_value=state), \
                patch("handwriting_grader.azure_ai.AzureClient", side_effect=AssertionError("Offline")):
            result = server.cluster_question(0)
        self.assertEqual(len(result["clusters"]), 1)
        self.assertEqual(result["model"], "cached-deployment")

        server.allow_ai = True
        server.embedding_cache = {}
        server.embedding_namespace = ENDPOINT
        server.embedding_cache_enabled = True
        server.shared_cache_path = self.root / "shared.json"
        fake = Mock()
        fake.embed_content.return_value = SimpleNamespace(
            embeddings=[SimpleNamespace(values=[1, 0])], usage_metadata=None
        )
        with patch.object(score_editor, "load_state", return_value=state), \
                patch.object(server, "get_embedding_client", return_value=(fake, "embedding-alias")):
            result = server.cluster_question(0)
        self.assertEqual(fake.embed_content.call_count, 2)
        self.assertEqual(len(result["clusters"]), 1)
        cached = json.loads((self.root / ".embedding_cache.json").read_text())
        self.assertEqual(cached["endpoint"], ENDPOINT)
        self.assertEqual(cached["model"], "embedding-alias")
        self.assertEqual(set(cached["embeddings"]), {"first", "second"})


if __name__ == "__main__":
    unittest.main()
