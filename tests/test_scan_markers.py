import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout, redirect_stderr
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from PIL import Image, ImageDraw, ImageFont
from openpyxl import Workbook
import yaml

from handwriting_grader.cli import main
from handwriting_grader.regions import atomic_json, file_hash
from handwriting_grader.scan_markers import (
    approve_markers, discover_markers, load_markers, marker_root, marker_snapshot,
    validate_markers,
)
from handwriting_grader.workflow import run_marker_workflow
from handwriting_grader.grading import grading_run_exists


def marker_data():
    return {"pages": [
        {"page_number": number, "markers": [
            {"text": text, "x": 80, "y": y, "width": 800, "height": 70}
            for text, y in zip(texts, (60, 180))
        ]}
        for number, texts in enumerate(
            [("Question One", "Explain Photosynthesis"), ("Question Two", "Describe Respiration")], 1,
        )
    ]}


class ScanMarkerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.config = {
            "exam": {"name": "Test", "roster": "roster.xlsx", "roster_sheet": "Roster",
                     "scanned_pdf": "scan.pdf", "marking_scheme": "rubric.docx",
                     "output_dir": "output"},
            "layout": {"pages_per_student": 2, "same_layout_for_all": True},
        }
        self.pages = []
        font = ImageFont.load_default(size=32)
        for page in marker_data()["pages"]:
            image = Image.new("RGB", (800, 1000), "white")
            draw = ImageDraw.Draw(image)
            for marker in page["markers"]:
                draw.text((70, marker["y"] + 5), marker["text"], font=font, fill="black")
            # Different answer ink must not affect marker recognition.
            for y in range(400, 900, 20):
                draw.line((30, y, 760, y + 12), fill="black", width=3)
            self.pages.append(image)
        self.pages[0].save(self.root / "scan.pdf", save_all=True, append_images=self.pages[1:])
        book = Workbook()
        sheet = book.active
        sheet.title = "Roster"
        sheet.append(["ID", "NAME", "CLASS"])
        sheet.append(["001", "Example", "A"])
        book.save(self.root / "roster.xlsx")
        book.close()
        (self.root / "rubric.docx").write_bytes(b"fixture")
        self.exam = self.root / "exam.yaml"
        self.exam.write_text(yaml.safe_dump(self.config), encoding="utf-8")
        self.models = self.root / "models.yaml"
        self.models.write_text(yaml.safe_dump({"azure_openai": {}, "models": {"annotation": "gpt-5.4"}}))

    def prepare_review(self):
        root = marker_root(self.config, self.root)
        (root / "images").mkdir(parents=True)
        images = []
        for index, image in enumerate(self.pages, 1):
            path = root / "images" / f"page-{index:02d}.jpg"
            image.save(path)
            images.append(path)
        atomic_json(root / "manifest.json", {
            **marker_snapshot(self.config, self.root), "language": "eng",
            "image_sha256": [file_hash(path) for path in images],
        })
        atomic_json(root / "markers.json", marker_data())
        return root, images

    def test_unique_printed_markers_and_valid_boxes_are_required(self):
        data = marker_data()
        data["pages"][1]["markers"][0]["text"] = "question ONE!"
        with self.assertRaisesRegex(ValueError, "unique"):
            validate_markers(data, 2)

    def test_cost_only_grading_directory_is_not_treated_as_a_grading_run(self):
        root = self.root / "grading"
        root.mkdir()
        (root / "cost_report.xlsx").write_bytes(b"report")
        (root / "cost_summary.json").write_text("{}")
        self.assertFalse(grading_run_exists(root))
        (root / "manifest.json").write_text("{}")
        self.assertTrue(grading_run_exists(root))
        data = marker_data()
        data["pages"][0]["markers"][0]["width"] = 1000
        with self.assertRaisesRegex(ValueError, "box"):
            validate_markers(data, 2)

    def test_one_page_unique_multiword_marker_is_valid(self):
        data = marker_data()
        data["pages"][0]["markers"] = data["pages"][0]["markers"][:1]
        data["pages"][1]["markers"] = data["pages"][1]["markers"][:1]
        self.assertEqual(
            [len(page.markers) for page in validate_markers(data, 2).pages],
            [1, 1],
        )

    def test_approval_is_explicit_and_changes_invalidate_it(self):
        root, images = self.prepare_review()
        with self.assertRaisesRegex(ValueError, "approve-scan-markers"):
            load_markers(self.config, self.root)
        approve_markers(self.config, self.root)
        with self.assertRaisesRegex(ValueError, "already exists"):
            approve_markers(self.config, self.root)
        data = marker_data()
        data["pages"][0]["markers"][0]["text"] = "Other question"
        atomic_json(root / "markers.json", data)
        with self.assertRaisesRegex(ValueError, "no longer current"):
            load_markers(self.config, self.root)

    def test_approval_is_human_review_not_local_ocr(self):
        root, _ = self.prepare_review()
        with patch("subprocess.run", side_effect=AssertionError("No OCR")):
            approve_markers(self.config, self.root)
        self.assertTrue((root / "approval.json").is_file())

    def test_azure_generated_marker_approval_preserves_old_review(self):
        root, _ = self.prepare_review()
        manifest = json.loads((root / "manifest.json").read_text())
        manifest["model"] = "gpt-6.1-terra"
        (root / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        (root / "approval.json").write_text(json.dumps({
            "markers_sha256": "stale",
            "manifest_sha256": "stale",
        }), encoding="utf-8")
        approve_markers(self.config, self.root)
        self.assertEqual(len(list((root / "approval-history").glob("approval-*.json"))), 1)

    def test_removed_scan_and_alignment_options_are_rejected(self):
        for args in (["check-scans"], ["retry-grading", "--exam", str(self.exam), "--align-images"]):
            with self.subTest(args=args), redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as exc:
                main(args)
            self.assertEqual(exc.exception.code, 2)

    def test_paid_preview_does_not_run_workflow_or_create_artifacts(self):
        with patch("handwriting_grader.workflow.run_marker_workflow") as workflow, \
                redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            status = main([
                "suggest-scan-markers", "--exam", str(self.exam), "--model-config", str(self.models),
                "--endpoint", "https://school.openai.azure.com", "--api-version", "v1",
            ])
        self.assertEqual(status, 1)
        workflow.assert_not_called()
        self.assertFalse(marker_root(self.config, self.root).exists())

    def test_framework_returns_proposals_without_human_approval(self):
        with patch("handwriting_grader.scan_markers.inspect_marker_discovery"), \
                patch("handwriting_grader.scan_markers.discover_markers", return_value=self.root) as discover:
            result = run_marker_workflow(
                self.config, self.root, self.models, "https://school.openai.azure.com", "v1",
            )
        self.assertEqual(result, self.root)
        discover.assert_called_once()
        self.assertFalse((self.root / "approval.json").exists())

    def test_discovery_sends_only_first_script_and_preserves_proposals(self):
        client = Mock()
        client.generate_content.return_value = SimpleNamespace(
            parsed=marker_data(), usage_metadata=None,
        )
        with patch("handwriting_grader.scan_markers.AzureClient") as factory:
            factory.return_value.__enter__.return_value = client
            root = discover_markers(
                self.config, self.root, self.models, "https://school.openai.azure.com", "v1",
            )
        contents = client.generate_content.call_args.kwargs["contents"]
        from handwriting_grader.azure_ai import ImagePart
        self.assertEqual(sum(isinstance(part, ImagePart) for part in contents), 2)
        self.assertEqual(json.loads((root / "markers.json").read_text()), marker_data())
        self.assertFalse((root / "approval.json").exists())
        with self.assertRaisesRegex(ValueError, "already exists"):
            discover_markers(self.config, self.root, self.models, "https://school.openai.azure.com", "v1")

    def test_discovery_accepts_unique_printed_question_labels(self):
        valid = marker_data()
        valid["pages"][0]["markers"][0]["text"] = "q12e"
        valid["pages"][1]["markers"][0]["text"] = "q39a"
        client = Mock()
        client.generate_content.return_value = SimpleNamespace(
            parsed=valid, usage_metadata=None,
        )
        with patch("handwriting_grader.scan_markers.AzureClient") as factory:
            factory.return_value.__enter__.return_value = client
            discover_markers(
                self.config, self.root, self.models,
                "https://school.openai.azure.com", "v1",
            )
        root = marker_root(self.config, self.root)
        self.assertTrue((root / "manifest.json").exists())
        self.assertEqual(json.loads((root / "markers.json").read_text()), valid)

    def test_confirmed_framework_discovery_is_included_in_cost_report(self):
        from handwriting_grader.azure_ai import Usage
        client = Mock()
        client.generate_content.return_value = SimpleNamespace(
            parsed=marker_data(), usage_metadata=Usage(100, 50, 150),
        )
        with patch("handwriting_grader.scan_markers.AzureClient") as factory, \
                redirect_stdout(io.StringIO()):
            factory.return_value.__enter__.return_value = client
            status = main([
                "suggest-scan-markers", "--exam", str(self.exam), "--model-config", str(self.models),
                "--endpoint", "https://school.openai.azure.com", "--api-version", "v1", "--confirm-cost",
            ])
        self.assertEqual(status, 0)
        output = io.StringIO()
        with redirect_stdout(output):
            self.assertEqual(main(["cost-report", "--exam", str(self.exam)]), 0)
        self.assertIn("Total API Calls:    1", output.getvalue())
        self.assertIn("UNPRICED", output.getvalue())
        self.assertFalse((marker_root(self.config, self.root) / "approval.json").exists())
