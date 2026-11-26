import io
import json
import shutil
import subprocess
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
    approve_markers, check_marker_pages, check_scanned_pages, discover_markers,
    load_markers, marker_root, marker_snapshot, require_tesseract, validate_markers,
)
from handwriting_grader.workflow import run_marker_workflow


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
        data = marker_data()
        data["pages"][0]["markers"][0]["width"] = 1000
        with self.assertRaisesRegex(ValueError, "box"):
            validate_markers(data, 2)

    def test_approval_is_explicit_and_changes_invalidate_it(self):
        root, images = self.prepare_review()
        with self.assertRaisesRegex(ValueError, "approve-scan-markers"):
            load_markers(self.config, self.root)
        with patch("handwriting_grader.scan_markers.require_tesseract", return_value="tesseract"), \
                patch("handwriting_grader.scan_markers.check_marker_pages", return_value=[]):
            approve_markers(self.config, self.root)
            self.assertEqual(check_scanned_pages(self.config, self.root, images)[0], [])
            with self.assertRaisesRegex(ValueError, "already exists"):
                approve_markers(self.config, self.root)
        data = marker_data()
        data["pages"][0]["markers"][0]["text"] = "Other question"
        atomic_json(root / "markers.json", data)
        with self.assertRaisesRegex(ValueError, "no longer current"):
            load_markers(self.config, self.root)

    def test_unreadable_first_script_cannot_be_approved(self):
        root, _ = self.prepare_review()
        with patch("handwriting_grader.scan_markers.require_tesseract", return_value="tesseract"), \
                patch("handwriting_grader.scan_markers.check_marker_pages", return_value=["PDF page 1: unreadable"]):
            with self.assertRaisesRegex(ValueError, "not reliably readable"):
                approve_markers(self.config, self.root)
        self.assertFalse((root / "approval.json").exists())

    def test_missing_markers_block_check_scans_with_no_model_call(self):
        with patch("handwriting_grader.scan_markers.AzureClient") as client, \
                redirect_stderr(io.StringIO()):
            self.assertEqual(main(["check-scans", "--exam", str(self.exam)]), 1)
        client.assert_not_called()

    def test_paid_preview_does_not_run_workflow_or_create_artifacts(self):
        with patch("handwriting_grader.scan_markers.require_tesseract", return_value="tesseract"), \
                patch("handwriting_grader.workflow.run_marker_workflow") as workflow, \
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
        with patch("handwriting_grader.scan_markers.require_tesseract", return_value="tesseract"), \
                patch("handwriting_grader.scan_markers.AzureClient") as factory:
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

    def test_missing_language_or_failed_engine_is_explicit(self):
        with patch("handwriting_grader.scan_markers.shutil.which", return_value=None):
            with self.assertRaisesRegex(ValueError, "Install Tesseract"):
                require_tesseract("eng")
        with patch("handwriting_grader.scan_markers.shutil.which", return_value="tesseract"), \
                patch("handwriting_grader.scan_markers.subprocess.run", return_value=subprocess.CompletedProcess(
                    [], 0, "List of available languages:\nosd\n", "",
                )):
            with self.assertRaisesRegex(ValueError, "language data"):
                require_tesseract("eng")

    def test_confirmed_framework_discovery_is_included_in_cost_report(self):
        from handwriting_grader.azure_ai import Usage
        client = Mock()
        client.generate_content.return_value = SimpleNamespace(
            parsed=marker_data(), usage_metadata=Usage(100, 50, 150),
        )
        with patch("handwriting_grader.scan_markers.require_tesseract", return_value="tesseract"), \
                patch("handwriting_grader.scan_markers.AzureClient") as factory, \
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

    def test_ambiguous_printed_markers_do_not_pass(self):
        _, images = self.prepare_review()
        markers = validate_markers(marker_data(), 2)
        all_text = " ".join(marker.text.casefold() for page in markers.pages for marker in page.markers)
        with patch("handwriting_grader.scan_markers.ocr_marker", return_value=all_text):
            issues = check_marker_pages(images, markers, "tesseract", "eng")
        self.assertEqual(len(issues), 2)
        self.assertTrue(all("ambiguous" in issue for issue in issues))

    @unittest.skipUnless(shutil.which("tesseract"), "Local Tesseract is not installed")
    def test_real_local_ocr_ignores_answers_and_flags_swaps_rotation_and_missing_text(self):
        executable = require_tesseract("eng")
        _, valid = self.prepare_review()
        markers = validate_markers(marker_data(), 2)
        self.assertEqual(check_marker_pages(valid, markers, executable, "eng"), [])
        issues = check_marker_pages(list(reversed(valid)), markers, executable, "eng")
        self.assertEqual(len(issues), 2)
        self.assertTrue(all("out of sequence" in issue for issue in issues))
        rotated = self.root / "rotated.jpg"
        self.pages[0].rotate(180).save(rotated)
        issues = check_marker_pages([rotated, valid[1]], markers, executable, "eng")
        self.assertEqual(len(issues), 1)
        self.assertIn("180 degrees", issues[0])
        self.pages[0].rotate(90, expand=True).save(rotated)
        issues = check_marker_pages([rotated, valid[1]], markers, executable, "eng")
        self.assertEqual(len(issues), 1)
        self.assertIn("270 degrees", issues[0])
        blank = self.root / "blank.jpg"
        Image.new("RGB", (800, 1000), "white").save(blank)
        issues = check_marker_pages([blank, valid[1]], markers, executable, "eng")
        self.assertEqual(len(issues), 1)
        self.assertIn("unreadable", issues[0])
