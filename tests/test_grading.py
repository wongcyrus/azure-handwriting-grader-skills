import base64
import io
import importlib.util
import json
import os
import select
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from contextlib import redirect_stdout
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

import yaml
from openpyxl import Workbook, load_workbook
from PIL import Image
from pypdf import PdfReader, PdfWriter
from docx import Document
from pptx import Presentation
from matplotlib.axes import Axes

from handwriting_grader.advanced import create_analysis
from handwriting_grader.analytics import question_boxplots, question_passing_policy
from handwriting_grader.cli import check_exam, main
from handwriting_grader.grade_review import approve_grading, read_approved_grading, validate_review
from handwriting_grader.grading import AzureGrader, approved_inputs, grade_exam, resume_grading, retry_grading, safe_append
from handwriting_grader.regions import atomic_json, file_hash, prepare_regions, verify_run
from handwriting_grader.reporting import passing_policy, passing_rows, report_rows, sample_rows, write_workbooks
from handwriting_grader.rubric import approve_rubric, import_rubric, write_rubric
from handwriting_grader.score_editor import ScoreServer


class FakeGrader:
    def __init__(self, models, endpoint, api_version):
        self.ids = iter(["001", "002"])

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        pass

    def ocr(self, image, field):
        if field == "ID":
            return next(self.ids)
        if field == "NAME":
            return "Example name"
        return "A" if field == "CLASS" else "Example answer"

    def grade(self, question, answer="", image=None):
        return {"answer": "Example answer", "mark": 1.0, "similarity_score": 0.5, "reasoning": "Example"}

    def moderate(self, question, entries):
        return {
            entry["script_index"]: {
                "script_index": entry["script_index"],
                "moderated_mark": entry["mark"],
                "flag": entry["script_index"] == 0,
                "note": "Check" if entry["script_index"] == 0 else "",
            }
            for entry in entries
        }


class GroupedAnswerOrderingTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which("node"), "Node.js is required")
    def test_similarity_labels_describe_displayed_values(self):
        editor = Path(__file__).resolve().parents[1] / "src" / "handwriting_grader" / "score_editor.html"
        script = """
const fs = require("fs"), vm = require("vm"), assert = require("assert");
const source = fs.readFileSync(process.argv[1], "utf8");
const start = source.indexOf("function updateSimilarityLabels(");
const end = source.indexOf("\\nfunction moveBlankZeroAnswersLast(", start);
assert(start >= 0 && end > start);
const elements = {"similarity-label": {parentElement: {}}, "similarity-toggle": {}};
vm.runInNewContext(source.slice(start, end) + `
  updateSimilarityLabels(true);
  if (byId("similarity-label").textContent !== "Group Similarity") throw Error("group label");
  if (byId("similarity-toggle").textContent !== "Group Similarity") throw Error("group toggle");
  if (byId("similarity-label").parentElement.title !==
      "Click to sort by answer similarity and exit grouped view") throw Error("group sort title");
  updateSimilarityLabels(false);
`, {byId: id => elements[id]});
assert.strictEqual(elements["similarity-label"].textContent, "Answer Similarity");
assert.strictEqual(elements["similarity-toggle"].textContent, "Answer Similarity");
assert.strictEqual(elements["similarity-label"].parentElement.title, "Click to sort by answer similarity");
"""
        subprocess.run([shutil.which("node"), "-e", script, str(editor)], check=True, capture_output=True, text=True)

    @unittest.skipUnless(shutil.which("node"), "Node.js is required")
    def test_blank_zero_answers_move_last_without_hiding_unscored_items(self):
        editor = Path(__file__).resolve().parents[1] / "src" / "handwriting_grader" / "score_editor.html"
        script = """
const fs = require("fs"), vm = require("vm"), assert = require("assert");
const source = fs.readFileSync(process.argv[1], "utf8");
const start = source.indexOf("function moveBlankZeroAnswersLast(");
const end = source.indexOf("\\nlet allStatusIncompleteOnly", start);
assert(start >= 0 && end > start);
vm.runInThisContext(source.slice(start, end));
const item = (id, answer, score, hasScore = true, needsManual = false) =>
  ({id, answer, score, hasScore, needsManual});
for (const model of ["Word Overlap", "text-embedding-3-small"]) {
  const clusters = [
    {repText: "(empty)", model, items: [
      item("blank-zero", "", 0), item("unscored", "", 0, false),
      item("needs-manual", "", 0, true, true), item("blank-positive", "", 1)
    ]},
    {repText: "answer", model, items: [item("zero-answer", "incorrect", 0)]},
    {repText: "", model, items: [item("whitespace-zero", "  ", 0)]}
  ];
  const result = moveBlankZeroAnswersLast(clusters);
  assert.deepStrictEqual(result.map(c => c.items.map(i => i.id)),
    [["unscored", "needs-manual", "blank-positive"], ["zero-answer"],
     ["blank-zero", "whitespace-zero"]]);
  assert.strictEqual(result[1].ungrouped, true);
  assert.strictEqual(result[2].blankZero, true);
  assert.strictEqual(clusters[0].items.length, 4);
  const separated = moveBlankZeroAnswersLast([
    {items: [item("first", "one", 1)]},
    {items: [item("same-a", "same", 1), item("same-b", "same", 1)]},
    {items: [item("second", "two", 1)]},
    {items: [item("blank", "", 0)]}
  ]);
  assert.deepStrictEqual(separated.map(c => c.items.map(i => i.id)),
    [["same-a", "same-b"], ["first", "second"], ["blank"]]);
  assert.strictEqual(separated[1].ungrouped, true);
  assert.strictEqual(separated[2].blankZero, true);
}
"""
        subprocess.run([shutil.which("node"), "-e", script, str(editor)], check=True, capture_output=True, text=True)

    @unittest.skipUnless(shutil.which("node"), "Node.js is required")
    def test_confirm_question_blocks_invalid_marks_including_hidden_rows(self):
        editor = Path(__file__).resolve().parents[1] / "src" / "handwriting_grader" / "score_editor.html"
        script = """
const fs = require("fs"), vm = require("vm"), assert = require("assert");
const source = fs.readFileSync(process.argv[1], "utf8");
const start = source.indexOf('byId("mark-question-reviewed").onclick =');
const end = source.indexOf("\\nasync function loadTableImages()", start);
assert(start >= 0 && end > start);
let calls = 0, status = "";
const elements = {"mark-question-reviewed": {}, "inline-mark-0": {value: "1"},
  "review-workspace": {scrollTop: 500}};
const mark = value => ({manual_mark: null, moderated_mark: value, raw_mark: value,
  answer: "", reasoning: "", reviewed: false, grading_failed: false, moderator_flag: false});
const state = {revision: "test", questions: [{question_number: "Q1", marks: 2}],
  scripts: [{script_index: 0}, {script_index: 1}], marks: [[mark(1)], [mark(null)]]};
const context = {state, section: "0", byId: id => elements[id] || null,
  message: text => status = text, setBusy: () => {}, updateRevision: () => {},
  reload: async () => { state.marks.forEach(row => row[0].reviewed = true); },
  api: async () => { calls++; return {json: async () => ({revision: "new"})}; },
  document: {activeElement: null}, render: async () => {}};
vm.runInNewContext(source.slice(start, end), context);
(async () => {
  await elements["mark-question-reviewed"].onclick();
  assert.strictEqual(calls, 0);
  assert.match(status, /#2 \\(empty\\)/);
  assert.strictEqual(elements["review-workspace"].scrollTop, 500);
  state.marks[1][0].moderated_mark = 0;
  elements["inline-mark-0"].value = "  ";
  await elements["mark-question-reviewed"].onclick();
  assert.strictEqual(calls, 0);
  assert.match(status, /#1 \\(empty\\)/);
  for (const [value, reason] of [["abc", "not numeric"], ["-1", "outside"], ["3", "outside"]]) {
    elements["inline-mark-0"].value = value;
    await elements["mark-question-reviewed"].onclick();
    assert.strictEqual(calls, 0);
    assert(status.includes(reason));
  }
  elements["inline-mark-0"].value = "1";
  state.marks[1][0].moderated_mark = 3;
  await elements["mark-question-reviewed"].onclick();
  assert.strictEqual(calls, 0);
  assert.match(status, /#2 \\(outside/);
  state.marks[1][0].moderated_mark = 0;
  await elements["mark-question-reviewed"].onclick();
  assert.strictEqual(calls, 1);
  assert.strictEqual(elements["review-workspace"].scrollTop, 500);
  state.questions.push({question_number: "Q2", marks: 2});
  state.marks.forEach(row => { row[0].reviewed = false; row.push(mark(1)); });
  await elements["mark-question-reviewed"].onclick();
  assert.strictEqual(calls, 2);
  assert.strictEqual(context.section, "1");
  assert.strictEqual(elements["review-workspace"].scrollTop, 0);
})().catch(error => { console.error(error); process.exitCode = 1; });
"""
        subprocess.run([shutil.which("node"), "-e", script, str(editor)], check=True, capture_output=True, text=True)


def prepare_scan_marker_fixture(test, config, config_dir):
    from handwriting_grader.scan_markers import marker_root, marker_snapshot

    root = marker_root(config, config_dir)
    (root / "images").mkdir(parents=True, exist_ok=True)
    count = config["layout"]["pages_per_student"]
    images = []
    for index in range(count):
        image = root / "images" / f"page-{index + 1:02d}.jpg"
        shutil.copyfile(config_dir / config["exam"]["output_dir"] / "regions" / "images" / f"{index}.jpg", image)
        images.append(image)
    atomic_json(root / "manifest.json", {
        **marker_snapshot(config, config_dir), "language": "eng",
        "image_sha256": [file_hash(image) for image in images],
    })
    atomic_json(root / "markers.json", {"pages": [
        {"page_number": index + 1, "markers": [
            {"text": f"Page {index + 1} marker {number}", "x": 0, "y": number * 100,
             "width": 500, "height": 50}
            for number in (1, 2)
        ]}
        for index in range(count)
    ]})
    atomic_json(root / "approval.json", {
        "manifest_sha256": file_hash(root / "manifest.json"),
        "markers_sha256": file_hash(root / "markers.json"),
    })
    atomic_json(root / "azure_confirmation-v2.json", {
        "version": 2,
        "pdf_sha256": file_hash(config_dir / config["exam"]["scanned_pdf"]),
        "marker_approval_sha256": file_hash(root / "approval.json"),
        "crop_count": len(PdfReader(config_dir / config["exam"]["scanned_pdf"]).pages) * 2,
        "issues": [],
    })
    for name, value in (("require_tesseract", "tesseract"), ("check_marker_pages", [])):
        mock = patch(f"handwriting_grader.scan_markers.{name}", return_value=value)
        mock.start()
        test.addCleanup(mock.stop)


class GradingTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        book = Workbook()
        sheet = book.active
        sheet.title = "Roster"
        sheet.append(["ID", "NAME", "CLASS"])
        sheet.append(["001", "One", "A"])
        sheet.append(["002", "Two", "A"])
        book.save(self.root / "roster.xlsx")
        book.close()
        from PIL import Image, ImageDraw
        pages = []
        for idx in range(4):
            img = Image.new("RGB", (200, 300), "white")
            draw = ImageDraw.Draw(img)
            for y_off in range(2, 100, 6):
                draw.line([(0, y_off), (200, y_off)], fill="black", width=2)
            if idx % 2 == 0:
                draw.rectangle([(20, 140), (180, 210)], fill="black")
            else:
                draw.ellipse([(40, 220), (160, 285)], fill="black")
            pages.append(img)
        pages[0].save(self.root / "scan.pdf", save_all=True, append_images=pages[1:], resolution=72.0)
        write_rubric(self.root / "source.xlsx", [{
            "question_number": "Q1", "question_text": "Question",
            "marking_scheme": "Award two marks", "marks": 2,
        }])
        self.config = {
            "exam": {
                "name": "Example", "roster": "roster.xlsx", "roster_sheet": "Roster",
                "scanned_pdf": "scan.pdf", "marking_scheme": "source.xlsx", "output_dir": "output",
            },
            "layout": {"pages_per_student": 2, "same_layout_for_all": True},
        }
        self.exam = self.root / "exam.yaml"
        self.exam.write_text(yaml.safe_dump(self.config))
        self.models = self.root / "models.yaml"
        self.models.write_text(yaml.safe_dump({
            "azure_openai": {},
            "models": {"ocr": "gpt-5.4-mini", "grading": "gpt-5.4-mini", "moderation": "gpt-5.4"},
        }))
        _, self.summary = check_exam(self.config, self.root)
        import_rubric(self.config, self.root, self.exam)
        approve_rubric(self.config, self.root, self.exam)
        regions = prepare_regions(self.config, self.root, 2)
        _, manifest = verify_run(self.config, self.root, self.exam)
        boxes = [
            {"x": i * 40, "y": 10, "width": 30, "height": 30, "label": label}
            for i, label in enumerate(["NAME", "ID", "CLASS", "1"])
        ]
        annotations = {"0": boxes, "1": []}
        atomic_json(regions / "draft.json", {"revision": 1, "annotations": annotations, "reviewed": [0, 1]})
        atomic_json(regions / "annotations.json", annotations)
        atomic_json(regions / "approval.json", {
            "annotations_sha256": file_hash(regions / "annotations.json"),
            "config_sha256": manifest["config_sha256"], "pdf_sha256": manifest["pdf_sha256"],
            "revision": 1,
        })
        prepare_scan_marker_fixture(self, self.config, self.root)

    def run_grading(self, provider=FakeGrader):
        return grade_exam(self.config, self.root, self.exam, self.models, "https://test.openai.azure.com", "v1",
                          self.summary, provider_factory=provider)

    def test_unreadable_scan_markers_block_before_paid_grading(self):
        from unittest.mock import Mock
        provider = Mock()
        confirmation = self.root / "output" / "scan-markers" / "azure_confirmation-v2.json"
        data = json.loads(confirmation.read_text(encoding="utf-8"))
        data["issues"] = ["PDF page 3: unreadable printed markers"]
        atomic_json(confirmation, data)
        with self.assertRaisesRegex(ValueError, "PDF page 3"):
            self.run_grading(provider)
        provider.assert_not_called()
        self.assertFalse((self.root / "output" / "grading").exists())

    def test_changed_marker_review_invalidates_grading_run(self):
        self.run_grading()
        atomic_json(self.root / "output" / "scan-markers" / "approval.json", {})
        from handwriting_grader.grade_review import verify_grading_run
        with self.assertRaisesRegex(ValueError, "approval is no longer current"):
            verify_grading_run(self.config, self.root, self.exam)

    def fill_review(self, path, *, flagged_override=1):
        book = load_workbook(path)
        scripts = book["Scripts"]
        for index, student in enumerate(("001", "002"), start=2):
            scripts.cell(index, 4, student)
            scripts.cell(index, 5, "yes")
        marks = book["Marks"]
        for row in range(2, 4):
            marks.cell(row, 12, "yes")
            if flagged_override is not None and marks.cell(row, 1).value == 0:
                marks.cell(row, 11, flagged_override)
            elif flagged_override is None and marks.cell(row, 1).value == 0:
                marks.cell(row, 11, None)
        book.save(path)
        book.close()

    def start_score_editor(self):
        self.score_server = ScoreServer(self.config, self.root, config_path=self.exam)
        thread = threading.Thread(target=self.score_server.serve_forever, daemon=True)
        thread.start()

        def cleanup():
            self.score_server.shutdown()
            thread.join(timeout=5)
            self.score_server.server_close()

        self.addCleanup(cleanup)

    def score_request(self, path, body=None, *, token=True, origin=True, host=None):
        headers = {}
        if token:
            headers["Authorization"] = f"Bearer {self.score_server.token}"
        if host is not None:
            headers["Host"] = host
        if body is not None:
            headers["Content-Type"] = "application/json"
            if origin:
                headers["Origin"] = self.score_server.origin
            body = json.dumps(body).encode()
        request = urllib.request.Request(self.score_server.origin + path, data=body, headers=headers)
        try:
            response = urllib.request.urlopen(request, timeout=15)
        except urllib.error.HTTPError as error:
            response = error
        with response:
            return response.status, response.read()

    def test_alignment_retry_restores_original_pages_and_preserves_history(self):
        root = self.run_grading()
        self.fill_review(root / "review.xlsx")
        review_hash = file_hash(root / "review.xlsx")
        pristine_hash = file_hash(root / "images" / "0.jpg")
        results_before = json.loads((root / "results.json").read_text())
        with Image.open(root / "images" / "0.jpg") as image:
            shifted = image.transform(
                image.size, Image.Transform.AFFINE, (1, 0, 0, 0, 1, -40),
                fillcolor=(255, 255, 255),
            )
        shifted.save(root / "images" / "0.jpg", format="JPEG", quality=95)
        damaged_hash = file_hash(root / "images" / "0.jpg")
        manifest = json.loads((root / "manifest.json").read_text())
        manifest["image_sha256"][0] = damaged_hash
        atomic_json(root / "manifest.json", manifest)

        with patch("handwriting_grader.grading.AzureClient", side_effect=AssertionError("No AI needed")):
            retry_grading(self.config, self.root, self.exam, self.summary, align_images=True)

        self.assertEqual(file_hash(root / "images" / "0.jpg"), pristine_hash)
        self.assertEqual(json.loads((root / "results.json").read_text()), results_before)
        backup, = (root / "alignment-history").iterdir()
        self.assertEqual(file_hash(backup / "images" / "0.jpg"), damaged_hash)
        self.assertEqual(file_hash(backup / "review.xlsx"), review_hash)
        restored_manifest = json.loads((root / "manifest.json").read_text())
        self.assertEqual(restored_manifest["image_sha256"][0], pristine_hash)
        self.assertTrue(restored_manifest["aligned_to_regions"])

    def test_write_review_never_regenerates_an_existing_workbook(self):
        from handwriting_grader.grading import write_review

        root = self.run_grading()
        results = json.loads((root / "results.json").read_text())
        book = load_workbook(root / "review.xlsx")
        try:
            book["Marks"]["K2"] = 0
            book.save(root / "review.xlsx")
        finally:
            book.close()
        original = (root / "review.xlsx").read_bytes()
        with self.assertRaisesRegex(ValueError, "cannot be regenerated"):
            write_review(root / "review.xlsx", results, overwrite=True)
        self.assertEqual((root / "review.xlsx").read_bytes(), original)
        invalid = root / "invalid.xlsx"
        invalid.write_bytes(b"not a workbook")
        with self.assertRaisesRegex(ValueError, "cannot be regenerated"):
            write_review(invalid, results, overwrite=True)
        self.assertEqual(invalid.read_bytes(), b"not a workbook")

    def test_failed_review_creation_can_resume_without_more_model_calls(self):
        root = self.run_grading()
        (root / "review.xlsx").unlink()

        def partial_save(book, destination):
            destination.write(b"partial workbook")
            raise OSError("synthetic workbook write failure")

        with patch("openpyxl.workbook.workbook.Workbook.save", autospec=True, side_effect=partial_save):
            with self.assertRaisesRegex(OSError, "synthetic workbook write failure"):
                resume_grading(self.config, self.root, self.exam, self.summary, provider_factory=FakeGrader)
        self.assertFalse((root / "review.xlsx").exists())
        with patch("handwriting_grader.grading.continue_grading",
                   side_effect=AssertionError("Completed grading must not call a model")):
            resume_grading(self.config, self.root, self.exam, self.summary, provider_factory=FakeGrader)
        self.assertTrue((root / "review.xlsx").is_file())

    def test_retry_preserves_teacher_edits_and_reopens_changed_question(self):
        class RetryProvider(FakeGrader):
            def grade(self, question, answer="", image=None):
                return {"answer": "New answer", "mark": 2, "similarity_score": 0.9,
                        "reasoning": "New reasoning"}

        root = self.run_grading()
        self.fill_review(root / "review.xlsx")
        book = load_workbook(root / "review.xlsx")
        try:
            book["Marks"]["D2"] = "Teacher correction"
            book["Marks"]["G2"] = "Teacher explanation"
            book["Marks"]["K2"] = 0
            book["Marks"]["N1"] = "teacher note"
            book["Marks"]["N2"] = "Keep this"
            book.save(root / "review.xlsx")
        finally:
            book.close()
        old_hash = file_hash(root / "review.xlsx")
        with patch("handwriting_grader.local_filter.is_blank_cell", return_value=False):
            retry_grading(self.config, self.root, self.exam, self.summary,
                          provider_factory=RetryProvider, question="Q1")
        book = load_workbook(root / "review.xlsx")
        try:
            self.assertEqual(book["Marks"]["D2"].value, "Teacher correction")
            self.assertEqual(book["Marks"]["G2"].value, "Teacher explanation")
            self.assertEqual(book["Marks"]["K2"].value, 0)
            self.assertEqual(book["Marks"]["N2"].value, "Keep this")
            self.assertEqual(book["Marks"]["D3"].value, "New answer")
            self.assertEqual(book["Marks"]["G3"].value, "New reasoning")
            self.assertIsNone(book["Marks"]["L2"].value)
            self.assertIsNone(book["Marks"]["L3"].value)
            self.assertEqual(book["Scripts"]["E2"].value, "yes")
        finally:
            book.close()
        self.assertEqual(file_hash(root / "review-history" / f"{old_hash}.xlsx"), old_hash)
        with self.assertRaisesRegex(ValueError, "Every mark needs explicit human review"):
            validate_review(self.config, self.root, self.exam)

    def test_interrupted_retry_keeps_edits_but_invalidates_affected_review(self):
        class FailingProvider(FakeGrader):
            def grade(self, question, answer="", image=None):
                raise RuntimeError("synthetic provider failure")

        root = self.run_grading()
        self.fill_review(root / "review.xlsx")
        book = load_workbook(root / "review.xlsx")
        try:
            book["Marks"]["D2"] = "Teacher correction"
            book.save(root / "review.xlsx")
        finally:
            book.close()
        with patch("handwriting_grader.local_filter.is_blank_cell", return_value=False):
            with self.assertRaisesRegex(RuntimeError, "synthetic provider failure"):
                retry_grading(self.config, self.root, self.exam, self.summary,
                              provider_factory=FailingProvider, question="Q1")
        book = load_workbook(root / "review.xlsx")
        try:
            self.assertEqual(book["Marks"]["D2"].value, "Teacher correction")
            self.assertIsNone(book["Marks"]["L2"].value)
            self.assertIsNone(book["Marks"]["L3"].value)
        finally:
            book.close()

    def test_partial_retry_checkpoint_cannot_reuse_old_review(self):
        class PartiallyFailingProvider(FakeGrader):
            def __init__(self, *args):
                super().__init__(*args)
                self.calls = 0

            def grade(self, question, answer="", image=None):
                self.calls += 1
                if self.calls == 2:
                    raise RuntimeError("synthetic second request failure")
                return {"answer": "Recovered answer", "mark": 1, "similarity_score": 0.8,
                        "reasoning": "Recovered reasoning"}

        root = self.run_grading()
        self.fill_review(root / "review.xlsx")
        results = json.loads((root / "results.json").read_text())
        for mark in results["marks"]:
            mark.update(raw_mark=None, moderated_mark=None, grading_failed=True)
        atomic_json(root / "results.json", results)
        with patch("handwriting_grader.local_filter.is_blank_cell", return_value=False):
            with self.assertRaisesRegex(RuntimeError, "second request failure"):
                retry_grading(self.config, self.root, self.exam, self.summary,
                              provider_factory=PartiallyFailingProvider)
        persisted = json.loads((root / "results.json").read_text())
        self.assertEqual(persisted["marks"][0]["answer"], "Recovered answer")
        self.assertTrue(persisted["marks"][1]["grading_failed"])
        book = load_workbook(root / "review.xlsx")
        try:
            self.assertIsNone(book["Marks"]["L2"].value)
            self.assertIsNone(book["Marks"]["L3"].value)
        finally:
            book.close()
        with self.assertRaisesRegex(ValueError, "Every mark needs explicit human review"):
            validate_review(self.config, self.root, self.exam)

    def test_retry_reopens_only_identities_for_metadata_ocr(self):
        root = self.run_grading()
        self.fill_review(root / "review.xlsx")
        retry_grading(self.config, self.root, self.exam, self.summary,
                      provider_factory=FakeGrader, re_ocr_fields=["ID"])
        book = load_workbook(root / "review.xlsx")
        try:
            self.assertEqual(book["Scripts"]["D2"].value, "001")
            self.assertIsNone(book["Scripts"]["E2"].value)
            self.assertIsNone(book["Scripts"]["E3"].value)
            self.assertEqual(book["Marks"]["L2"].value, "yes")
            self.assertEqual(book["Marks"]["L3"].value, "yes")
        finally:
            book.close()

    def test_retry_keeps_unaffected_questions_reviewed(self):
        from handwriting_grader.grading import _update_retry_review

        root = self.run_grading()
        self.fill_review(root / "review.xlsx")
        results = json.loads((root / "results.json").read_text())
        book = load_workbook(root / "review.xlsx")
        try:
            for row in list(book["Marks"].iter_rows(min_row=2, values_only=True)):
                new_row = list(row)
                new_row[1] = "Q2"
                book["Marks"].append(new_row)
            book.save(root / "review.xlsx")
        finally:
            book.close()
        results["marks"].extend([{**row, "question": "Q2"} for row in results["marks"]])
        _update_retry_review(root / "review.xlsx", results, results, set(), {"1"},
                             file_hash(root / "review.xlsx"), prepare=True)
        book = load_workbook(root / "review.xlsx")
        try:
            self.assertIsNone(book["Marks"]["L2"].value)
            self.assertIsNone(book["Marks"]["L3"].value)
            self.assertEqual(book["Marks"]["L4"].value, "yes")
            self.assertEqual(book["Marks"]["L5"].value, "yes")
        finally:
            book.close()

    def test_retry_stops_if_workbook_changes_during_provider_call(self):
        root = self.run_grading()
        self.fill_review(root / "review.xlsx")

        class ConcurrentEditProvider(FakeGrader):
            def moderate(self, question, entries):
                book = load_workbook(root / "review.xlsx")
                try:
                    book["Marks"]["D2"] = "Concurrent edit"
                    book.save(root / "review.xlsx")
                finally:
                    book.close()
                return super().moderate(question, entries)

        with patch("handwriting_grader.local_filter.is_blank_cell", return_value=False):
            with self.assertRaisesRegex(ValueError, "changed during retry"):
                retry_grading(self.config, self.root, self.exam, self.summary,
                              provider_factory=ConcurrentEditProvider, question="Q1")
        book = load_workbook(root / "review.xlsx")
        try:
            self.assertEqual(book["Marks"]["D2"].value, "Concurrent edit")
            self.assertIsNone(book["Marks"]["L2"].value)
        finally:
            book.close()

    def test_retry_preview_includes_possible_answer_ocr_calls(self):
        from handwriting_grader.grading import inspect_retry_grading

        self.run_grading()
        info = inspect_retry_grading(self.config, self.root, self.exam, question="Q1")
        self.assertEqual(info["estimated_requests"], 5)

    def test_retry_rejects_malformed_review_before_provider(self):
        from unittest.mock import Mock

        root = self.run_grading()
        book = load_workbook(root / "review.xlsx")
        try:
            book["Marks"]["K2"] = "=1+1"
            book.save(root / "review.xlsx")
        finally:
            book.close()
        original = (root / "review.xlsx").read_bytes()
        provider = Mock()
        with self.assertRaisesRegex(ValueError, "cannot contain formulas"):
            retry_grading(self.config, self.root, self.exam, self.summary,
                          provider_factory=provider, question="Q1")
        provider.assert_not_called()
        self.assertEqual((root / "review.xlsx").read_bytes(), original)

    def test_score_editor_security_concurrency_and_review_invalidation(self):
        root = self.run_grading()
        self.fill_review(root / "review.xlsx")
        approve_grading(self.config, self.root, self.exam)
        with patch("handwriting_grader.score_editor.shared_embedding_cache_path",
                   return_value=self.root / "shared_embed_cache.json"):
            self.start_score_editor()
        self.assertEqual(self.score_request("/api/state", token=False)[0], 403)
        self.assertEqual(self.score_request("/api/state", host="evil.example")[0], 403)
        self.assertEqual(self.score_request("/api/save", {}, origin=False)[0], 403)
        status, content = self.score_request("/api/state")
        self.assertEqual(status, 200)
        state = json.loads(content)
        revision = state["revision"]
        self.assertEqual(state["marks"][0][0]["similarity_score"], 0.5)
        workbook_hash = file_hash(root / "review.xlsx")
        suggestion = {"revision": revision, "script_index": 0, "question_index": 0,
                      "threshold": ".8", "step": ".3"}
        status, content = self.score_request("/api/suggest", suggestion)
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(content)["suggestion"], "0.9")
        self.assertEqual(file_hash(root / "review.xlsx"), workbook_hash)
        self.assertEqual(self.score_request("/api/suggest", {**suggestion, "step": "0"})[0], 400)
        self.assertEqual(self.score_request("/api/suggest", {**suggestion, "step": "1e-999999"})[0], 400)
        status, image = self.score_request("/api/image/0/0")
        self.assertEqual(status, 200)
        self.assertEqual(image[:8], b"\x89PNG\r\n\x1a\n")
        self.assertEqual(self.score_request("/api/image/0/full-0")[1][:3], b"\xff\xd8\xff")
        self.assertEqual(self.score_request("/api/image/0/../../review.xlsx")[0], 404)
        change = {
            "revision": revision, "kind": "mark", "script_index": 0, "question_index": 0,
            "answer": "=1+1", "reasoning": "Reviewed", "manual_mark": "", "reviewed": True,
        }
        original_results = (root / "results.json").read_bytes()
        altered = json.loads(original_results)
        altered["marks"][0]["answer"] = "Changed outside the editor"
        (root / "results.json").write_text(json.dumps(altered))
        self.assertEqual(self.score_request("/api/save", change)[0], 409)
        (root / "results.json").write_bytes(original_results)
        self.assertEqual(self.score_request("/api/save", change)[0], 400)
        lock = root / ".score-review.lock"
        lock.write_text("test")
        self.assertEqual(self.score_request("/api/save", change)[0], 409)
        lock.unlink()
        change["manual_mark"] = "2"
        status, content = self.score_request("/api/save", change)
        self.assertEqual(status, 200, content)
        self.assertEqual(self.score_request("/api/save", change)[0], 409)
        self.assertEqual(file_hash(root / "review-history" / f"{workbook_hash}.xlsx"), workbook_hash)
        with self.assertRaisesRegex(ValueError, "changed since approval"):
            read_approved_grading(self.config, self.root, self.exam)
        book = load_workbook(root / "review.xlsx", data_only=False)
        try:
            self.assertEqual(book["Marks"]["D2"].value, "=1+1")
            self.assertEqual(book["Marks"]["D2"].data_type, "s")
        finally:
            book.close()
        state = json.loads(self.score_request("/api/state")[1])
        self.assertIn("has_clusters", state)
        self.assertFalse(state["has_clusters"])
        self.assertEqual(self.score_request("/api/suggest", {**suggestion, "revision": state["revision"]})[0], 400)
        self.assertEqual(self.score_request("/api/approve", {"revision": state["revision"]})[0], 400)
        self.assertEqual(self.score_request("/api/approve", {
            "revision": state["revision"], "confirmed": True,
        })[0], 200)
        self.assertEqual(read_approved_grading(self.config, self.root, self.exam)[2]["marks"][0]["answer"], "=1+1")

    def test_score_editor_save_batch_applies_multiple_items_atomically(self):
        self.run_grading()
        self.start_score_editor()
        state = json.loads(self.score_request("/api/state")[1])
        batch_items = [
            {"script_index": 0, "kind": "script", "reviewed_id": "001", "reviewed": True},
            {"script_index": 1, "kind": "script", "reviewed_id": "002", "reviewed": True},
            {"script_index": 0, "kind": "mark", "question_index": 0, "answer": "A1", "reasoning": "R1", "manual_mark": "2", "reviewed": True},
            {"script_index": 1, "kind": "mark", "question_index": 0, "answer": "A2", "reasoning": "R2", "manual_mark": "1", "reviewed": True},
        ]
        status, body = self.score_request("/api/save-batch", {"revision": state["revision"], "items": batch_items})
        self.assertEqual(status, 200)
        self.assertIn("revision", json.loads(body))
        updated = json.loads(self.score_request("/api/state")[1])
        self.assertTrue(updated["scripts"][0]["reviewed"])
        self.assertTrue(updated["scripts"][1]["reviewed"])
        self.assertEqual(updated["scripts"][0]["reviewed_id"], "001")
        self.assertEqual(updated["marks"][0][0]["manual_mark"], 2)
        self.assertTrue(updated["marks"][0][0]["reviewed"])

    def test_score_editor_reset_review_backs_up_and_restores_fresh_state(self):
        root = self.run_grading()
        self.fill_review(root / "review.xlsx")
        approve_grading(self.config, self.root, self.exam)
        self.assertTrue((root / "approval.json").is_file())
        self.start_score_editor()
        state = json.loads(self.score_request("/api/state")[1])
        self.assertTrue(all(s["reviewed"] for s in state["scripts"]))
        self.assertEqual(self.score_request("/api/reset", {"revision": state["revision"], "confirmed": False})[0], 400)
        status, body = self.score_request("/api/reset", {"revision": state["revision"], "confirmed": True})
        self.assertEqual(status, 200)
        self.assertIn("revision", json.loads(body))
        self.assertFalse((root / "approval.json").exists())
        self.assertTrue(any((root / "review-history").glob("*.xlsx")))
        fresh = json.loads(self.score_request("/api/state")[1])
        self.assertTrue(all(not s["reviewed"] for s in fresh["scripts"]))
        self.assertTrue(all(not fresh["marks"][s["script_index"]][0]["reviewed"] for s in fresh["scripts"]))

    def test_score_editor_reset_does_not_overwrite_concurrent_review(self):
        from handwriting_grader.grading import write_review

        root = self.run_grading()
        self.fill_review(root / "review.xlsx")
        approve_grading(self.config, self.root, self.exam)
        self.start_score_editor()
        state = json.loads(self.score_request("/api/state")[1])

        def change_during_reset(*args, **kwargs):
            write_review(*args, **kwargs)
            book = load_workbook(root / "review.xlsx")
            try:
                book["Marks"]["D2"] = "Concurrent teacher edit"
                book.save(root / "review.xlsx")
            finally:
                book.close()

        with patch("handwriting_grader.grading.write_review", side_effect=change_during_reset):
            status, body = self.score_request("/api/reset", {"revision": state["revision"], "confirmed": True})
        self.assertEqual(status, 409, body)
        self.assertTrue((root / "approval.json").exists())
        book = load_workbook(root / "review.xlsx")
        try:
            self.assertEqual(book["Marks"]["D2"].value, "Concurrent teacher edit")
        finally:
            book.close()

    def test_score_editor_cli_starts_and_serves_review(self):
        self.run_grading()
        command = [sys.executable, "-c", "from handwriting_grader.cli import main; raise SystemExit(main())",
                   "review-grading", "--exam", str(self.exam)]
        process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        try:
            if os.name == "nt":
                line = process.stdout.readline().strip()
            else:
                ready, _, _ = select.select([process.stdout], [], [], 15)
                self.assertTrue(ready, "CLI editor did not become ready")
                line = process.stdout.readline().strip()
            self.assertTrue(line.startswith("Open http://127.0.0.1:"), line)
            url, token = line.removeprefix("Open ").split("#", 1)
            request = urllib.request.Request(url + "api/state", headers={"Authorization": "Bearer " + token})
            with urllib.request.urlopen(request, timeout=15) as response:
                self.assertEqual(response.status, 200)
                self.assertEqual(len(json.load(response)["scripts"]), 2)
        finally:
            if process.poll() is None:
                process.terminate()
            process.communicate(timeout=10)

    def test_score_editor_handles_older_results_without_similarity(self):
        root = self.run_grading()
        results = json.loads((root / "results.json").read_text())
        for mark in results["marks"]:
            del mark["similarity_score"]
        (root / "results.json").write_text(json.dumps(results))
        with patch("handwriting_grader.score_editor.shared_embedding_cache_path",
                   return_value=self.root / "shared_embed_cache.json"):
            self.start_score_editor()
        state = json.loads(self.score_request("/api/state")[1])
        self.assertIsNone(state["marks"][0][0]["similarity_score"])
        status, content = self.score_request("/api/suggest", {
            "revision": state["revision"], "script_index": 0, "question_index": 0,
            "threshold": ".8", "step": ".25",
        })
        self.assertEqual(status, 400)
        self.assertIn("Similarity is unavailable", json.loads(content)["error"])

    def test_bulk_similarity_preview_and_explicit_unreviewed_drafts(self):
        root = self.run_grading()
        self.fill_review(root / "review.xlsx")
        approve_grading(self.config, self.root, self.exam)
        with patch("handwriting_grader.score_editor.shared_embedding_cache_path",
                   return_value=self.root / "shared_embed_cache.json"):
            self.start_score_editor()
        state = json.loads(self.score_request("/api/state")[1])
        request = {"revision": state["revision"], "question_index": 0, "threshold": ".8", "step": ".25"}
        original_hash = file_hash(root / "review.xlsx")
        self.assertEqual(self.score_request("/api/bulk-apply", {**request, "confirmed": True})[0], 400)
        status, response = self.score_request("/api/bulk-preview", request)
        self.assertEqual(status, 200)
        preview = json.loads(response)
        self.assertEqual([x["suggestion"] for x in preview["suggestions"]], ["1.00", "1.00"])
        self.assertEqual(file_hash(root / "review.xlsx"), original_hash)
        selected = [{"script_index": 0, "suggestion": "1.00"}]
        apply = {**request, "preview_token": preview["preview_token"], "selected": selected, "confirmed": True}
        self.assertEqual(self.score_request("/api/bulk-apply", {**apply, "confirmed": False})[0], 400)
        self.assertEqual(self.score_request("/api/bulk-apply", {**apply, "selected": [
            {"script_index": 0, "suggestion": "2"}]})[0], 400)
        self.assertEqual(self.score_request("/api/bulk-apply", apply)[0], 200)
        self.assertEqual(file_hash(root / "review-history" / f"{original_hash}.xlsx"), original_hash)
        workbook = load_workbook(root / "review.xlsx")
        try:
            self.assertEqual(workbook["Marks"]["K2"].value, 1)
            self.assertIsNone(workbook["Marks"]["L2"].value)
            self.assertEqual(workbook["Marks"]["L3"].value, "yes")
        finally:
            workbook.close()
        with self.assertRaises(ValueError):
            read_approved_grading(self.config, self.root, self.exam)
        self.assertEqual(self.score_request("/api/bulk-apply", apply)[0], 400)
        new_state = json.loads(self.score_request("/api/state")[1])
        stale = {**request, "revision": new_state["revision"]}
        self.assertEqual(self.score_request("/api/bulk-preview", request)[0], 409)
        status, response = self.score_request("/api/bulk-preview", stale)
        self.assertEqual(status, 200)

    def test_bulk_similarity_excludes_corrected_answers(self):
        root = self.run_grading()
        self.fill_review(root / "review.xlsx")
        workbook = load_workbook(root / "review.xlsx")
        workbook["Marks"]["D3"] = "Corrected"
        workbook.save(root / "review.xlsx")
        workbook.close()
        with patch("handwriting_grader.score_editor.shared_embedding_cache_path",
                   return_value=self.root / "shared_embed_cache.json"):
            self.start_score_editor()
        state = json.loads(self.score_request("/api/state")[1])
        request = {"revision": state["revision"], "question_index": 0, "threshold": ".8", "step": ".25"}
        status, response = self.score_request("/api/bulk-preview", request)
        self.assertEqual(status, 200)
        preview = json.loads(response)
        self.assertIsNone(preview["suggestions"][1]["suggestion"])
        self.assertIn("original OCR", preview["suggestions"][1]["error"])
        before = file_hash(root / "review.xlsx")
        status, _ = self.score_request("/api/bulk-apply", {
            **request, "preview_token": preview["preview_token"], "confirmed": True,
            "selected": [{"script_index": 1, "suggestion": "1.00"}],
        })
        self.assertEqual(status, 400)
        self.assertEqual(file_hash(root / "review.xlsx"), before)

    def test_adjusted_crop_preview_is_bounded_and_read_only(self):
        root = self.run_grading()
        with patch("handwriting_grader.score_editor.shared_embedding_cache_path",
                   return_value=self.root / "shared_embed_cache.json"):
            self.start_score_editor()
        state = json.loads(self.score_request("/api/state")[1])
        before = {name: file_hash(root / name) for name in ("review.xlsx", "results.json", "manifest.json")}
        request = {"revision": state["revision"], "script_index": 0, "question_index": 0,
                   "x": 1, "y": 2, "width": 15, "height": 20}
        status, content = self.score_request("/api/preview-crop", request)
        self.assertEqual(status, 200)
        with Image.open(io.BytesIO(content)) as image:
            self.assertEqual(image.size, (15, 20))
        for invalid in ({"x": -1}, {"width": 0}, {"x": 999999}, {"height": 1.5}):
            self.assertEqual(self.score_request("/api/preview-crop", {**request, **invalid})[0], 400)
        self.assertEqual(self.score_request("/api/preview-crop", {**request, "revision": "stale"})[0], 409)
        self.assertEqual(before, {name: file_hash(root / name) for name in before})
        self.assertFalse((root / "approval.json").exists())

    @unittest.skipUnless(
        importlib.util.find_spec("playwright") and shutil.which("google-chrome"),
        "Playwright and Google Chrome are required",
    )
    def test_score_editor_browser_reviews_and_approves(self):
        from playwright.sync_api import sync_playwright

        self.run_grading()
        with patch("handwriting_grader.score_editor.shared_embedding_cache_path",
                   return_value=self.root / "shared_embed_cache.json"):
            self.start_score_editor()
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(executable_path=shutil.which("google-chrome"), headless=True)
            try:
                page = browser.new_page()
                page.on("dialog", lambda dialog: dialog.accept())
                page.goto(f"{self.score_server.origin}/#{self.score_server.token}")
                page.wait_for_function("Boolean(state) && !busy")
                self.assertNotIn(self.score_server.token, page.url)
                for index, student in enumerate(("001", "002")):
                    page.locator("#section").select_option("id")
                    page.locator("#marksheet-tbody select").nth(index).select_option(student)
                    page.get_by_text(f"Script #{index + 1} identity saved and reviewed.").wait_for()
                page.get_by_role("button", name="Q1").click()
                page.locator("#inline-mark-0").fill("2")
                page.locator("#inline-mark-0").press("Enter")
                page.get_by_text("Script #1 saved and reviewed.").wait_for()
                page.locator("#inline-ans-0").fill("Corrected answer")
                page.locator("#inline-rev-0").click()
                page.get_by_text("Script #1 saved and reviewed.").wait_for()
                page.locator("#inline-rev-1").click()
                page.get_by_text("Script #2 saved and reviewed.").wait_for()
                page.locator("#review-menu > summary").click()
                page.locator("#approve").click()
                page.locator("#kb-confirm-ok").click()
                page.get_by_text("Approved 2 students and 2 marks.").wait_for()
                reviewed = read_approved_grading(self.config, self.root, self.exam)
                self.assertEqual(reviewed[2]["marks"][0]["answer"], "Corrected answer")
                self.assertEqual(reviewed[6][(0, "1")], 2)
            finally:
                browser.close()

    @unittest.skipUnless(
        importlib.util.find_spec("playwright") and shutil.which("google-chrome"),
        "Playwright and Google Chrome are required",
    )
    def test_score_editor_keyboard_navigation_and_group_mark(self):
        from playwright.sync_api import sync_playwright

        self.run_grading()
        self.start_score_editor()
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(executable_path=shutil.which("google-chrome"), headless=True)
            try:
                page = browser.new_page()
                page.goto(f"{self.score_server.origin}/#{self.score_server.token}")
                page.wait_for_function("Boolean(state) && !busy")
                page.get_by_role("button", name="Q1").click()
                self.assertEqual(page.locator("#similarity-label").inner_text(), "Answer Similarity")
                page.evaluate("""() => {
                    state.has_clusters = true;
                    const select = document.getElementById("marksheet-cluster-mode");
                    select.querySelector('[value="embedding"]').disabled = false;
                    select.value = "embedding";
                    qClusterCache.set(0, {method: "embedding", model: "test", clusters: [
                        {id: 1, rep_text: "Example answer", scripts: [
                            {script_index: 0, similarity: 1}, {script_index: 1, similarity: 0.9}
                        ]}
                    ]});
                    renderMarksheetTable();
                }""")
                self.assertEqual(page.locator("#similarity-label").inner_text(), "Group Similarity")
                self.assertIn("Avg Group Similarity:", page.locator(".group-divider").first.inner_text())
                page.select_option("#marksheet-cluster-mode", "words")
                self.assertEqual(page.locator("#similarity-label").inner_text(), "Answer Similarity")
                self.assertIn("Avg Answer Similarity:", page.locator(".group-divider").first.inner_text())
                self.assertFalse(page.locator("#status").is_visible())
                page.evaluate("""() => {
                    document.getElementById("q-banner-title").textContent = "Long question ".repeat(100);
                }""")
                title = page.locator("#q-banner-title")
                self.assertTrue(page.locator("#q-banner-scheme").is_visible())
                self.assertGreater(title.bounding_box()["height"], 20)
                page.locator("#q-banner > summary").click()
                self.assertTrue(title.evaluate("(el) => el.scrollWidth > el.clientWidth"))
                self.assertFalse(page.locator("#q-banner-scheme").is_visible())
                page.locator("#q-banner > summary").click()
                self.assertTrue(page.locator("#q-banner-scheme").is_visible())
                page.locator("#q-banner > summary").click()
                self.assertFalse(page.locator("#review-menu").evaluate("(el) => el.open"))
                page.locator("#review-menu > summary").click()
                self.assertTrue(page.locator("#approve").is_visible())
                page.locator("#review-menu > summary").click()
                page.locator("#inline-mark-0").fill("2")
                page.locator("#inline-mark-0").press("Enter")
                page.get_by_text("Script #1 saved and reviewed.").wait_for()
                page.wait_for_function("document.activeElement.id === 'inline-mark-1'")
                page.locator("#inline-mark-1").fill("0")
                page.locator("#inline-mark-1").press("ArrowUp")
                page.get_by_text("Script #2 saved and reviewed.").wait_for()
                page.wait_for_function("document.activeElement.id === 'inline-mark-0'")
                page.locator("#inline-mark-0").fill("3")
                page.locator("#inline-mark-0").press("ArrowDown")
                page.get_by_text("Manual mark is outside the question's range").wait_for()
                page.wait_for_function("document.activeElement.id === 'inline-mark-0'")
                self.assertEqual(page.locator("#inline-mark-0").input_value(), "3")

                page.locator("#inline-mark-0").fill("2")
                page.locator("#inline-mark-0").press("Enter")
                page.get_by_text("Script #1 saved and reviewed.").wait_for()
                group_mark = page.get_by_label("Mark for Similar Group 1")
                group_mark.fill("1")
                page.get_by_role("button", name="Apply group mark").click()
                self.assertIn("2 reviewed answer(s) will become unreviewed", page.locator("#kb-confirm-text").inner_text())
                page.locator("#kb-confirm-ok").click()
                page.get_by_text("Saved 2 group marks. Review each affected answer.").wait_for()
                state = json.loads(self.score_request("/api/state")[1])
                self.assertEqual([state["marks"][i][0]["manual_mark"] for i in range(2)], [1, 1])
                self.assertTrue(all(not state["marks"][i][0]["reviewed"] for i in range(2)))

                page.get_by_label("Mark for Similar Group 1").fill("0")
                page.get_by_role("button", name="Apply group mark").click()
                page.locator("#kb-confirm-cancel").click()
                self.assertEqual(json.loads(self.score_request("/api/state")[1])["revision"], state["revision"])

                page.evaluate("""() => {
                    state.scripts.push({...state.scripts[0], script_index: 2});
                    state.marks[2] = [{...state.marks[0][0], answer: "Unrelated"}];
                    renderMarksheetTable();
                }""")
                rows = page.locator("#marksheet-tbody > tr")
                self.assertEqual(rows.count(), 5)
                self.assertIn("Similar Group 1", rows.nth(0).inner_text())
                self.assertIn("Ungrouped answers", rows.nth(3).inner_text())
                self.assertEqual(rows.nth(3).locator("input").count(), 0)

                page.evaluate("""() => {
                    const tbody = document.getElementById("marksheet-tbody");
                    for (let i = 0; i < 15; i++) {
                        const row = document.createElement("tr");
                        const cell = document.createElement("td");
                        cell.colSpan = 7;
                        cell.style.height = "150px";
                        row.append(cell);
                        tbody.append(row);
                    }
                }""")
                page.locator("#review-workspace").scroll_into_view_if_needed()
                before = page.locator("#review-pinned").bounding_box()
                page.locator("#review-workspace").evaluate("(el) => { el.scrollTop = 1000; }")
                page.wait_for_function("document.getElementById('review-workspace').scrollTop > 0")
                after = page.locator("#review-pinned").bounding_box()
                header = page.locator("#marksheet th").first.bounding_box()
                self.assertAlmostEqual(before["y"], after["y"], delta=1)
                self.assertAlmostEqual(after["y"] + after["height"], header["y"], delta=2)
                self.assertTrue(page.locator("#mark-question-reviewed").is_visible())
            finally:
                browser.close()

    @unittest.skipUnless(
        importlib.util.find_spec("playwright") and shutil.which("google-chrome"),
        "Playwright and Google Chrome are required",
    )
    def test_marksheet_table_escapes_html_and_navigates_review(self):
        from playwright.sync_api import sync_playwright

        root = self.run_grading()
        self.fill_review(root / "review.xlsx", flagged_override=2)
        workbook = load_workbook(root / "review.xlsx")
        workbook["Marks"]["D3"] = '<img src=x onerror="window.injected=true">'
        workbook.save(root / "review.xlsx")
        workbook.close()
        before = file_hash(root / "review.xlsx")
        with patch("handwriting_grader.score_editor.shared_embedding_cache_path",
                   return_value=self.root / "shared_embed_cache.json"):
            self.start_score_editor()
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(executable_path=shutil.which("google-chrome"), headless=True)
            try:
                page = browser.new_page()
                page.goto(f"{self.score_server.origin}/#{self.score_server.token}")
                page.wait_for_function("Boolean(state) && !busy")
                page.get_by_role("button", name="Q1").click()
                self.assertEqual(page.locator("#marksheet-tbody tr").count(), 2)
                self.assertIn('<img src=x', page.locator("#inline-ans-1").input_value())
                page.locator("#marksheet-tbody td strong", has_text="#2").click()
                self.assertEqual(page.locator("#script").input_value(), "1")
                self.assertEqual(page.locator("#section").input_value(), "0")
                self.assertIsNone(page.evaluate("window.injected"))
            finally:
                browser.close()
        self.assertEqual(file_hash(root / "review.xlsx"), before)
        self.assertFalse((root / "approval.json").exists())

    @unittest.skipUnless(
        importlib.util.find_spec("playwright") and shutil.which("google-chrome"),
        "Playwright and Google Chrome are required",
    )
    def test_browser_crop_adjustment_is_only_a_visual_preview(self):
        from playwright.sync_api import sync_playwright

        root = self.run_grading()
        before = file_hash(root / "review.xlsx")
        with patch("handwriting_grader.score_editor.shared_embedding_cache_path",
                   return_value=self.root / "shared_embed_cache.json"):
            self.start_score_editor()
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(executable_path=shutil.which("google-chrome"), headless=True)
            try:
                page = browser.new_page()
                page.goto(f"{self.score_server.origin}/#{self.score_server.token}")
                page.wait_for_function("Boolean(state) && !busy")
                page.get_by_role("button", name="Q1").click()
                page.locator("#marksheet-tbody img.answer-crop-img").first.click()
                page.locator("#image-modal[open]").wait_for()
                page.wait_for_function("() => document.querySelector('#modal-img').naturalWidth > 0")
            finally:
                browser.close()
        self.assertEqual(file_hash(root / "review.xlsx"), before)

    def test_preview_requires_consent_and_real_prerequisites(self):
        models = yaml.safe_load(self.models.read_text())
        models["caching"] = {"enabled": True, "scope": "shared", "agents": {"annotation": True}}
        self.models.write_text(yaml.safe_dump(models))
        arguments = [
            "grade", "--exam", str(self.exam), "--model-config", str(self.models),
            "--endpoint", "https://test.openai.azure.com", "--api-version", "v1",
        ]
        output = io.StringIO()
        with patch("handwriting_grader.grading.grade_exam") as run, redirect_stdout(output):
            self.assertEqual(main(arguments), 1)
            run.assert_not_called()
        self.assertIn("Cache: disabled; directory=none", output.getvalue())
        self.assertIn("Up to 10 requests", output.getvalue())
        self.assertFalse((self.root / "output" / "grading").exists())
        output = io.StringIO()
        with patch("handwriting_grader.grading.grade_exam") as run, redirect_stdout(output):
            self.assertEqual(main(arguments + ["--mode", "item"]), 1)
            run.assert_not_called()
        self.assertIn("Up to 11 requests", output.getvalue())

    def test_review_diagnostics_reports_multiple_issues_without_approval(self):
        root = self.run_grading()
        self.fill_review(root / "review.xlsx")
        workbook = load_workbook(root / "review.xlsx")
        workbook["Scripts"]["D3"] = "001"
        workbook["Marks"]["K2"] = None
        workbook["Marks"]["L3"] = None
        workbook.save(root / "review.xlsx")
        workbook.close()
        before = {name: file_hash(root / name) for name in ("review.xlsx", "results.json", "manifest.json")}
        output = io.StringIO()
        with redirect_stdout(output):
            result = main(["check-grading-review", "--exam", str(self.exam)])
        self.assertEqual(result, 1)
        self.assertIn("duplicate roster ID", output.getvalue())
        self.assertIn("1 present roster ID(s) not assigned", output.getvalue())
        self.assertIn("manual mark required", output.getvalue())
        self.assertIn("mark not reviewed", output.getvalue())
        self.assertEqual(before, {name: file_hash(root / name) for name in before})
        self.assertFalse((root / "approval.json").exists())
        self.fill_review(root / "review.xlsx")
        output = io.StringIO()
        with redirect_stdout(output):
            self.assertEqual(main(["check-grading-review", "--exam", str(self.exam)]), 0)
        self.assertIn("explicit approval", output.getvalue())
        self.assertFalse((root / "approval.json").exists())

    def test_review_diagnostics_fails_closed_for_invalid_review_and_stale_inputs(self):
        root = self.run_grading()
        self.fill_review(root / "review.xlsx")
        workbook = load_workbook(root / "review.xlsx")
        workbook["Scripts"]["D2"] = "=1+1"
        workbook.save(root / "review.xlsx")
        workbook.close()
        output = io.StringIO()
        with redirect_stdout(output):
            self.assertEqual(main(["check-grading-review", "--exam", str(self.exam)]), 1)
        self.assertIn("cannot contain formulas", output.getvalue())
        self.assertFalse((root / "approval.json").exists())
        self.models.write_text(self.models.read_text() + "\n# changed\n")
        with redirect_stdout(io.StringIO()):
            self.assertEqual(main(["check-grading-review", "--exam", str(self.exam)]), 1)

    def test_review_diagnostics_finds_missing_rows_and_out_of_range_marks(self):
        root = self.run_grading()
        self.fill_review(root / "review.xlsx")
        workbook = load_workbook(root / "review.xlsx")
        workbook["Scripts"]["D3"] = "unknown"
        workbook["Marks"]["K2"] = 3
        workbook["Marks"].delete_rows(3)
        workbook.save(root / "review.xlsx")
        workbook.close()
        with redirect_stdout(io.StringIO()) as output:
            self.assertEqual(main(["check-grading-review", "--exam", str(self.exam)]), 1)
        self.assertIn("missing or unknown roster ID", output.getvalue())
        self.assertIn("mark missing or outside allowed range", output.getvalue())
        self.assertIn("missing mark row", output.getvalue())

    def test_grading_review_approval_and_input_invalidation(self):
        root = self.run_grading()
        results = json.loads((root / "results.json").read_text())
        self.assertTrue(results["completed"])
        self.assertEqual(len(results["scripts"]), 2)
        self.assertTrue(all(script["name_ocr"] == "Example name" for script in results["scripts"]))
        self.assertEqual(json.loads((root / "manifest.json").read_text())["metadata_fields"], ["ID", "CLASS", "NAME"])
        self.assertEqual(len(results["marks"]), 2)
        self.assertTrue(all(mark["similarity_score"] == 0.5 for mark in results["marks"]))
        workbook = load_workbook(root / "review.xlsx")
        try:
            self.assertEqual(workbook["Scripts"]["F2"].value, "Example name")
            self.assertEqual(workbook["Marks"]["M2"].value, 0.5)
        finally:
            workbook.close()
        self.assertTrue(next(m for m in results["marks"] if m["script_index"] == 0)["moderator_flag"])
        with self.assertRaisesRegex(ValueError, "explicit human review"):
            validate_review(self.config, self.root, self.exam)
        self.fill_review(root / "review.xlsx", flagged_override=None)
        with self.assertRaisesRegex(ValueError, "manual mark"):
            validate_review(self.config, self.root, self.exam)
        self.fill_review(root / "review.xlsx", flagged_override=3)
        with self.assertRaisesRegex(ValueError, "outside"):
            validate_review(self.config, self.root, self.exam)
        self.fill_review(root / "review.xlsx")
        self.assertEqual(approve_grading(self.config, self.root, self.exam), (2, 2))
        validated = read_approved_grading(self.config, self.root, self.exam)
        self.assertEqual(validated[6][(0, "1")], 1)
        self.models.write_text("changed")
        with self.assertRaisesRegex(ValueError, "inputs or approvals changed"):
            read_approved_grading(self.config, self.root, self.exam)

    def test_approved_grading_remains_valid_after_default_cleanup(self):
        from handwriting_grader.cleanup import archive_and_clean

        root = self.run_grading()
        self.fill_review(root / "review.xlsx")
        approve_grading(self.config, self.root, self.exam)
        archive_and_clean(self.config, self.root)
        self.assertTrue((root / "images").is_dir())
        self.assertTrue((root.parent / "regions" / "images").is_dir())
        self.assertEqual(read_approved_grading(self.config, self.root, self.exam)[6][(0, "1")], 1)

    def test_corrected_answers_require_manual_marks_and_flow_into_reports_and_analysis(self):
        root = self.run_grading()
        self.fill_review(root / "review.xlsx")
        workbook = load_workbook(root / "review.xlsx")
        marks = workbook["Marks"]
        marks["D3"] = "Corrected answer"
        marks["G3"] = "Teacher reasoning"
        workbook.save(root / "review.xlsx")
        workbook.close()
        with self.assertRaisesRegex(ValueError, "corrected answer requires a manual mark"):
            approve_grading(self.config, self.root, self.exam)
        workbook = load_workbook(root / "review.xlsx")
        workbook["Marks"]["K3"] = 2
        workbook.save(root / "review.xlsx")
        workbook.close()
        approve_grading(self.config, self.root, self.exam)
        self.assertEqual(main(["report", "--exam", str(self.exam)]), 0)
        workbook = load_workbook(root.parent / "reports" / "details_score_report.xlsx", read_only=True)
        try:
            self.assertEqual(workbook["Answers"]["D3"].value, "Corrected answer")
            self.assertEqual(workbook["Reasoning"]["D3"].value, "Teacher reasoning")
            self.assertEqual(workbook["AnswersRaw"]["C3"].value, "Example answer")
            self.assertEqual(workbook["ReasoningRaw"]["C3"].value, "Example")
            self.assertEqual(workbook["ReasoningRaw"]["F3"].value, 0.5)
            self.assertEqual(workbook["Marks"]["D3"].value, 2)
        finally:
            workbook.close()
        raw = json.loads((root / "results.json").read_text())
        self.assertEqual(raw["marks"][1]["answer"], "Example answer")
        self.assertEqual(raw["marks"][1]["reasoning"], "Example")

        model = self.root / "analysis-models.yaml"
        model.write_text(yaml.safe_dump({"azure_openai": {}, "models": {"analytics": "gpt-5.4"}}))

        class FakeAnalyst:
            calls = []

            def __init__(self, *args):
                pass

            def __enter__(self):
                return self

            def __exit__(self, *args):
                pass

            def analyze(self, task, data):
                self.calls.append((task, data))
                return "Feedback"

        create_analysis(self.config, self.root, self.exam, model, "https://test.openai.azure.com", "v1",
                        provider_factory=FakeAnalyst)
        details = FakeAnalyst.calls[1][1]["questions"][0]
        self.assertEqual(details["answer"], "Corrected answer")
        self.assertEqual(details["reviewed_reasoning"], "Teacher reasoning")
        self.assertEqual(details["reviewed_mark"], 2)

    def test_cleared_answer_requires_manual_mark(self):
        root = self.run_grading()
        self.fill_review(root / "review.xlsx")
        workbook = load_workbook(root / "review.xlsx")
        workbook["Marks"]["D3"] = None
        workbook.save(root / "review.xlsx")
        workbook.close()
        with self.assertRaisesRegex(ValueError, "corrected answer requires a manual mark"):
            validate_review(self.config, self.root, self.exam)
        workbook = load_workbook(root / "review.xlsx")
        workbook["Marks"]["K3"] = 0
        workbook.save(root / "review.xlsx")
        workbook.close()
        result = validate_review(self.config, self.root, self.exam)
        self.assertEqual(result[2]["marks"][1]["answer"], "")

    def test_excel_review_rejects_text_that_would_be_truncated(self):
        workbook = Workbook()
        try:
            with self.assertRaisesRegex(ValueError, "32,767-character"):
                safe_append(workbook.active, ["a" * 32768])
        finally:
            workbook.close()

    def test_failed_grading_is_not_accepted_as_zero(self):
        class FailingGrader(FakeGrader):
            def grade(self, question, answer):
                raise RuntimeError("Model unavailable")
        root = self.run_grading(FailingGrader)
        rows = json.loads((root / "results.json").read_text())["marks"]
        self.assertTrue(all(row["grading_failed"] and row["raw_mark"] is None for row in rows))
        self.fill_review(root / "review.xlsx")
        with self.assertRaisesRegex(ValueError, "manual mark"):
            validate_review(self.config, self.root, self.exam)

    def test_batch_recovery_bisects_and_preserves_review(self):
        from types import SimpleNamespace
        from handwriting_grader.azure_ai import AzureIncompleteResponse
        from handwriting_grader.batch_recovery import inspect_batch_recovery, recover_question_batches
        from handwriting_grader.grading import QuestionBatchGradeResponse, StudentBatchGradeItem
        from handwriting_grader.score_editor import load_state, save_review

        root = self.run_grading()
        results = json.loads((root / "results.json").read_text())
        for row in results["marks"]:
            row.update(answer="", reasoning="", raw_mark=None, moderated_mark=None,
                       moderator_flag=True, grading_failed=True)
        atomic_json(root / "results.json", results)
        book = load_workbook(root / "review.xlsx")
        for row in list(book["Marks"].iter_rows())[1:]:
            row[3].value = ""
            row[6].value = ""
        book.save(root / "review.xlsx")
        book.close()
        info = inspect_batch_recovery(self.config, self.root, self.exam, "Q1")
        self.assertEqual(info["max_requests"], 3)
        calls = []

        class FilterOne(FakeGrader):
            def grade_question_batch(self, question, items):
                indices = [item["script_index"] for item in items]
                calls.append(indices)
                if 0 in indices:
                    raise AzureIncompleteResponse("incomplete", "content_filter", "request-id")
                return QuestionBatchGradeResponse(grades=[
                    StudentBatchGradeItem(script_index=indices[0], answer="Recovered answer", mark=1,
                                          similarity_score=0.5, reasoning="Recovered reason")
                ])

        outcome = recover_question_batches(self.config, self.root, self.exam, "Q1", info["revision"], 3,
                                            provider_factory=FilterOne)
        self.assertEqual(calls, [[0, 1], [0], [1]])
        self.assertEqual((outcome["recovered"], outcome["blocked"], outcome["pending"]), (1, 1, 0))
        server = SimpleNamespace(config=self.config, config_dir=self.root, config_path=self.exam, run_id=None)
        _, revision, _, _, _, marks = load_state(server)
        self.assertTrue(marks[(0, "1")]["grading_failed"])
        self.assertEqual(marks[(1, "1")]["answer"], "Recovered answer")
        self.assertFalse(marks[(1, "1")]["reviewed"])
        save_review(server, {"revision": revision, "kind": "mark", "script_index": 1,
                             "question_index": 0, "answer": "", "reasoning": "",
                             "manual_mark": "", "reviewed": False})
        _, _, _, _, _, marks = load_state(server)
        self.assertEqual(marks[(1, "1")]["answer"], "")

    def test_embedding_preview_uses_separate_config_and_requires_current_revision(self):
        from types import SimpleNamespace
        from unittest.mock import Mock

        root = self.run_grading()
        embedding_config = self.root / "embedding.yaml"
        embedding_config.write_text(yaml.safe_dump({
            "azure_openai": {"endpoint": "https://test.openai.azure.com", "api_version": "v1"},
            "models": {"embedding": "text-embedding-3-small"},
        }))
        output = io.StringIO()
        args = ["cluster-answers", "--exam", str(self.exam), "--model-config", str(embedding_config)]
        with patch("handwriting_grader.azure_ai.AzureClient", side_effect=AssertionError("No Azure calls")), \
                redirect_stdout(output):
            self.assertEqual(main(args + ["--preview-embedding"]), 0)
            self.assertEqual(main(args), 0)
            self.assertEqual(main(args + ["--confirm-cost", "--revision", "stale"]), 1)
        self.assertIn("model=text-embedding-3-small", output.getvalue())
        self.assertIn("Review and grading revision:", output.getvalue())
        self.assertFalse((root / "clusters.json").exists())
        revision = output.getvalue().split("Review and grading revision: ", 1)[1].splitlines()[0]
        fake = Mock()
        fake.embed_content.return_value = SimpleNamespace(embeddings=[SimpleNamespace(values=[1.0, 0.0])])
        with patch.object(ScoreServer, "get_embedding_client", return_value=(fake, "text-embedding-3-small")):
            self.assertEqual(main(args + ["--confirm-cost", "--revision", revision]), 0)
        fake.embed_content.assert_called_once()
        saved = json.loads((root / "clusters.json").read_text())
        self.assertEqual(saved["Q1"]["method"], "embedding")
        self.assertTrue(saved["Q1"]["answer_hash"])
        self.assertFalse((root / ".embedding_cache.json").exists())

    def test_batch_recovery_does_not_overwrite_concurrent_review(self):
        from handwriting_grader.batch_recovery import inspect_batch_recovery, recover_question_batches
        from handwriting_grader.grading import QuestionBatchGradeResponse, StudentBatchGradeItem

        root = self.run_grading()
        results = json.loads((root / "results.json").read_text())
        for row in results["marks"]:
            row.update(answer="", reasoning="", raw_mark=None, moderated_mark=None,
                       moderator_flag=True, grading_failed=True)
        atomic_json(root / "results.json", results)
        book = load_workbook(root / "review.xlsx")
        for row in list(book["Marks"].iter_rows())[1:]:
            row[3].value = ""
            row[6].value = ""
        book.save(root / "review.xlsx")
        book.close()
        before = (root / "results.json").read_bytes()
        info = inspect_batch_recovery(self.config, self.root, self.exam, "Q1")

        class ConcurrentEdit(FakeGrader):
            def grade_question_batch(self, question, items):
                book = load_workbook(root / "review.xlsx")
                book["Marks"]["K2"] = 0
                book.save(root / "review.xlsx")
                book.close()
                return QuestionBatchGradeResponse(grades=[
                    StudentBatchGradeItem(script_index=item["script_index"], answer="Recovered",
                                          mark=1, similarity_score=0.5, reasoning="Reason")
                    for item in items
                ])

        with self.assertRaisesRegex(ValueError, "Review or grading changed"):
            recover_question_batches(self.config, self.root, self.exam, "Q1", info["revision"], 3,
                                     provider_factory=ConcurrentEdit)
        self.assertEqual((root / "results.json").read_bytes(), before)
        book = load_workbook(root / "review.xlsx")
        self.assertEqual(book["Marks"]["K2"].value, 0)
        book.close()

    def test_batch_recovery_finds_multiple_filtered_answers_and_obeys_limit(self):
        from handwriting_grader.azure_ai import AzureIncompleteResponse
        from handwriting_grader.batch_recovery import inspect_batch_recovery, recover_question_batches

        root = self.run_grading()
        results = json.loads((root / "results.json").read_text())
        for row in results["marks"]:
            row.update(answer="", reasoning="", raw_mark=None, moderated_mark=None,
                       moderator_flag=True, grading_failed=True)
        atomic_json(root / "results.json", results)
        book = load_workbook(root / "review.xlsx")
        for row in list(book["Marks"].iter_rows())[1:]:
            row[3].value = ""
            row[6].value = ""
        book.save(root / "review.xlsx")
        book.close()

        class FilterAll(FakeGrader):
            def grade_question_batch(self, question, items):
                raise AzureIncompleteResponse("incomplete", "content_filter", "request-id")

        info = inspect_batch_recovery(self.config, self.root, self.exam, "Q1")
        limited = recover_question_batches(self.config, self.root, self.exam, "Q1", info["revision"], 2,
                                           provider_factory=FilterAll)
        self.assertEqual((limited["requests"], limited["blocked"], limited["pending"]), (2, 1, 1))
        info = inspect_batch_recovery(self.config, self.root, self.exam, "Q1")
        full = recover_question_batches(self.config, self.root, self.exam, "Q1", info["revision"], 3,
                                        provider_factory=FilterAll)
        self.assertEqual((full["requests"], full["blocked"], full["pending"]), (3, 2, 0))

    def test_batch_recovery_keeps_successes_when_later_request_errors(self):
        from handwriting_grader.azure_ai import AzureIncompleteResponse
        from handwriting_grader.batch_recovery import inspect_batch_recovery, recover_question_batches
        from handwriting_grader.grading import QuestionBatchGradeResponse, StudentBatchGradeItem

        root = self.run_grading()
        results = json.loads((root / "results.json").read_text())
        for row in results["marks"]:
            row.update(answer="", reasoning="", raw_mark=None, moderated_mark=None,
                       moderator_flag=True, grading_failed=True)
        atomic_json(root / "results.json", results)
        book = load_workbook(root / "review.xlsx")
        for row in list(book["Marks"].iter_rows())[1:]:
            row[3].value = ""
            row[6].value = ""
        book.save(root / "review.xlsx")
        book.close()
        calls = []

        class FailAfterSuccess(FakeGrader):
            def grade_question_batch(self, question, items):
                indices = [item["script_index"] for item in items]
                calls.append(indices)
                if len(indices) > 1:
                    raise AzureIncompleteResponse("incomplete", "content_filter", "request-id")
                if indices == [1]:
                    raise ValueError("invalid response")
                return QuestionBatchGradeResponse(grades=[
                    StudentBatchGradeItem(script_index=0, answer="Recovered", mark=1,
                                          similarity_score=0.5, reasoning="Reason")
                ])

        info = inspect_batch_recovery(self.config, self.root, self.exam, "Q1")
        with self.assertRaisesRegex(ValueError, "changed after preview"):
            recover_question_batches(self.config, self.root, self.exam, "Q1", "stale", 3,
                                     provider_factory=FailAfterSuccess)
        self.assertEqual(calls, [])
        outcome = recover_question_batches(self.config, self.root, self.exam, "Q1", info["revision"], 3,
                                            provider_factory=FailAfterSuccess)
        self.assertEqual(calls, [[0, 1], [0], [1]])
        self.assertEqual((outcome["recovered"], outcome["pending"]), (1, 1))
        self.assertIn("invalid response", outcome["error"])
        rows = json.loads((root / "results.json").read_text())["marks"]
        self.assertEqual(rows[0]["answer"], "Recovered")
        self.assertTrue(rows[1]["grading_failed"])

    def test_interrupted_grading_resumes_without_repeating_checkpointed_marks(self):
        class InterruptedGrader(FakeGrader):
            calls = 0

            def grade(self, question, answer):
                type(self).calls += 1
                if self.calls == 2:
                    raise KeyboardInterrupt()
                return super().grade(question, answer)

        with self.assertRaises(KeyboardInterrupt):
            self.run_grading(InterruptedGrader)
        root = self.root / "output" / "grading"
        partial = json.loads((root / "results.json").read_text())
        self.assertEqual(len(partial["scripts"]), 2)
        self.assertEqual(len(partial["marks"]), 1)
        self.assertFalse((root / "processing.lock").exists())
        preview = io.StringIO()
        with patch("handwriting_grader.grading.resume_grading") as resume, redirect_stdout(preview):
            self.assertEqual(main(["resume-grading", "--exam", str(self.exam),
                                   "--continue-on-image-policy-block"]), 1)
            resume.assert_not_called()
        self.assertIn("0 metadata request(s) and 1 question request(s)", preview.getvalue())
        self.assertIn("flagged for manual review", preview.getvalue())
        preview = io.StringIO()
        with patch("handwriting_grader.grading.resume_grading") as resume, redirect_stdout(preview):
            self.assertEqual(main(["resume-grading", "--exam", str(self.exam), "--mode", "item"]), 1)
            resume.assert_not_called()
        self.assertIn("0 metadata request(s) and up to 3 item-mode", preview.getvalue())

        def fail_after_recording_usage(*args, **kwargs):
            self.assertTrue(kwargs["continue_on_image_policy_block"])
            from handwriting_grader.azure_ai import Usage
            from handwriting_grader.telemetry import get_active_tracker
            tracker = get_active_tracker()
            self.assertIsNotNone(tracker)
            tracker.record_call("ocr", "resume test", "test-model", Usage(10, 5, 15), 0.1)
            raise RuntimeError("simulated failure")

        with patch("handwriting_grader.grading.resume_grading", side_effect=fail_after_recording_usage):
            self.assertEqual(main(["resume-grading", "--exam", str(self.exam), "--confirm-cost",
                                   "--continue-on-image-policy-block"]), 1)
        usage = root / "telemetry" / "azure_usage.jsonl"
        self.assertEqual(len(usage.read_text(encoding="utf-8").splitlines()), 1)
        self.assertEqual(json.loads((root / "cost_summary.json").read_text())["total_calls"], 1)

        class ResumingGrader(FakeGrader):
            calls = 0

            def grade(self, question, answer):
                type(self).calls += 1
                return super().grade(question, answer)

        resume_grading(self.config, self.root, self.exam, self.summary, provider_factory=ResumingGrader)
        self.assertEqual(ResumingGrader.calls, 1)
        self.assertTrue(json.loads((root / "results.json").read_text())["completed"])
        self.assertTrue((root / "review.xlsx").is_file())
        with self.assertRaisesRegex(ValueError, "already exists"):
            resume_grading(self.config, self.root, self.exam, self.summary, provider_factory=ResumingGrader)

    def test_interrupted_grading_refuses_changed_inputs_and_stale_lock(self):
        class InterruptedGrader(FakeGrader):
            def grade(self, question, answer):
                raise KeyboardInterrupt()
        with self.assertRaises(KeyboardInterrupt):
            self.run_grading(InterruptedGrader)
        root = self.root / "output" / "grading"
        (root / "processing.lock").write_text("stale")
        with self.assertRaisesRegex(ValueError, "lock"):
            resume_grading(self.config, self.root, self.exam, self.summary, provider_factory=FakeGrader)
        (root / "processing.lock").unlink()
        self.models.write_text("changed")
        with self.assertRaisesRegex(ValueError, "inputs or approvals changed"):
            resume_grading(self.config, self.root, self.exam, self.summary, provider_factory=FakeGrader)

    def test_legacy_checkpoint_resume_does_not_add_name_ocr_calls(self):
        class InterruptedGrader(FakeGrader):
            def grade(self, question, answer):
                raise KeyboardInterrupt()

        with self.assertRaises(KeyboardInterrupt):
            self.run_grading(InterruptedGrader)
        root = self.root / "output" / "grading"
        manifest = json.loads((root / "manifest.json").read_text())
        del manifest["metadata_fields"]
        atomic_json(root / "manifest.json", manifest)
        results = json.loads((root / "results.json").read_text())
        for script in results["scripts"]:
            script.pop("name_ocr", None)
        atomic_json(root / "results.json", results)

        class ResumingGrader(FakeGrader):
            fields = []

            def ocr(self, image, field):
                type(self).fields.append(field)
                return super().ocr(image, field)

        resume_grading(self.config, self.root, self.exam, self.summary, provider_factory=ResumingGrader)
        self.assertNotIn("NAME", ResumingGrader.fields)
        with patch("handwriting_grader.score_editor.shared_embedding_cache_path",
                   return_value=self.root / "shared_embed_cache.json"):
            self.start_score_editor()
        state = json.loads(self.score_request("/api/state")[1])
        self.assertTrue(all(script["name_ocr"] is None for script in state["scripts"]))

    def test_rubric_and_regions_must_match(self):
        region_dir = self.root / "output" / "regions"
        draft = json.loads((region_dir / "draft.json").read_text())
        draft["annotations"]["0"][-1]["label"] = "2"
        atomic_json(region_dir / "draft.json", draft)
        atomic_json(region_dir / "annotations.json", draft["annotations"])
        approval = json.loads((region_dir / "approval.json").read_text())
        approval["annotations_sha256"] = file_hash(region_dir / "annotations.json")
        atomic_json(region_dir / "approval.json", approval)
        with self.assertRaisesRegex(ValueError, "do not match"):
            approved_inputs(self.config, self.root, self.exam)

    def test_reports_require_approval_and_use_reviewed_marks(self):
        from handwriting_grader.moodle import export_moodle

        root = self.run_grading()
        self.fill_review(root / "review.xlsx", flagged_override=2)
        arguments = ["report", "--exam", str(self.exam)]
        self.assertEqual(main(arguments), 1)
        self.assertFalse((root.parent / "reports").exists())
        approve_grading(self.config, self.root, self.exam)
        image_hash = file_hash(root / "images" / "0.jpg")
        self.assertEqual(main(arguments), 0)
        reports = root.parent / "reports"
        book = load_workbook(reports / "score_report.xlsx", read_only=True)
        try:
            rows = list(book["Marks"].values)
            self.assertEqual(rows[1], ("001", "One", "A", 2, "pdfs/001_One_script-00001.pdf"))
            self.assertEqual(rows[2][3], 1)
        finally:
            book.close()
        book = load_workbook(reports / "details_score_report.xlsx", read_only=True)
        try:
            self.assertEqual(book.sheetnames, ["Marks", "Answers", "Reasoning", "AnswersRaw", "ReasoningRaw"])
            self.assertEqual(book["Marks"]["D2"].value, 2)
            self.assertEqual(book["Marks"]["F2"].value, "pdfs/001_One_script-00001.pdf")
            self.assertEqual(book["Answers"]["D2"].value, "Example answer")
        finally:
            book.close()
        self.assertEqual(len(PdfReader(reports / "pdfs" / "001_One_script-00001.pdf").pages), 2)
        self.assertEqual(len(PdfReader(reports / "all.pdf").pages), 4)
        self.assertEqual(file_hash(root / "images" / "0.jpg"), image_hash)
        manifest = json.loads((reports / "manifest.json").read_text())
        self.assertTrue(manifest["completed"])
        self.assertEqual(manifest["version"], 2)
        self.assertIn("pdfs/001_One_script-00001.pdf", manifest["script_pdf_sha256"])
        export_moodle(self.config, self.root, self.exam)
        self.assertEqual(
            (root.parent / "moodle" / "student_pdfs" / "001_One.pdf").read_bytes(),
            (reports / "pdfs" / "001_One_script-00001.pdf").read_bytes(),
        )
        self.assertEqual(main(arguments), 1)

    def test_moodle_uses_approved_rubric_and_never_overwrites_export(self):
        from handwriting_grader.moodle import export_moodle, _render_feedback_cover_pdf

        root = self.run_grading()
        self.fill_review(root / "review.xlsx")
        approve_grading(self.config, self.root, self.exam)
        self.assertEqual(main(["report", "--exam", str(self.exam)]), 0)
        analysis = root.parent / "ai-analysis"
        analysis.mkdir()
        (analysis / "approval.json").write_text("{}")
        with patch("handwriting_grader.advanced.read_approved_analysis",
                   return_value=(None, None, {0: "Reviewed feedback"}, None, None, None)), \
             patch("handwriting_grader.moodle._render_feedback_cover_pdf",
                   wraps=_render_feedback_cover_pdf) as cover:
            output = export_moodle(self.config, self.root, self.exam)
        self.assertEqual(cover.call_args.args[5], 2)
        existing = (output / "student_pdfs" / "001_One.pdf").read_bytes()
        with patch("handwriting_grader.advanced.read_approved_analysis",
                   return_value=(None, None, {0: "Reviewed feedback"}, None, None, None)):
            with self.assertRaisesRegex(ValueError, "already exists"):
                export_moodle(self.config, self.root, self.exam)
        self.assertEqual((output / "student_pdfs" / "001_One.pdf").read_bytes(), existing)

    def test_moodle_rejects_stale_feedback_and_supports_child_selection(self):
        from handwriting_grader.moodle import export_moodle

        root = self.run_grading()
        self.fill_review(root / "review.xlsx")
        approve_grading(self.config, self.root, self.exam)
        self.assertEqual(main(["report", "--exam", str(self.exam)]), 0)
        analysis = root.parent / "ai-analysis"
        analysis.mkdir()
        (analysis / "approval.json").write_text("{}")
        with patch("handwriting_grader.advanced.read_approved_analysis",
                   side_effect=ValueError("stale analysis")):
            with self.assertRaisesRegex(ValueError, "stale analysis"):
                export_moodle(self.config, self.root, self.exam)
        self.assertFalse((root.parent / "moodle").exists())
        with patch("handwriting_grader.moodle.export_moodle", return_value=root / "child-moodle") as export:
            self.assertEqual(main(["moodle-export", "--exam", str(self.exam), "--run", "revision-1"]), 0)
        self.assertEqual(export.call_args.kwargs["run_id"], "revision-1")

    def test_moodle_safe_names_and_fractional_worksheet_grades(self):
        import csv
        import zipfile
        from handwriting_grader.distribution import approved_report
        from handwriting_grader.moodle import export_moodle

        root = self.run_grading()
        self.fill_review(root / "review.xlsx", flagged_override=0.125)
        approve_grading(self.config, self.root, self.exam)
        self.assertEqual(main(["report", "--exam", str(self.exam)]), 0)
        validated, rows, reports = approved_report(self.config, self.root, self.exam)
        collision_rows = [{**rows[0], "id": "0/01"}, {**rows[1], "id": "0\\01", "name": rows[0]["name"]}]
        with patch("handwriting_grader.moodle.approved_report", return_value=(validated, collision_rows, reports)):
            with self.assertRaisesRegex(ValueError, "duplicate Moodle filenames"):
                export_moodle(self.config, self.root, self.exam)
        self.assertFalse((root.parent / "moodle").exists())

        worksheet = self.root / "worksheet.csv"
        unsafe_rows = [{**rows[0], "id": "../001"}, rows[1]]
        worksheet.write_text("ID number,Identifier,Full name,Grade\n../001,Participant 1,../../One,\n",
                             encoding="utf-8")
        with patch("handwriting_grader.moodle.approved_report", return_value=(validated, unsafe_rows, reports)):
            output = export_moodle(self.config, self.root, self.exam, worksheet=worksheet)
        with (output / "grading_worksheet_filled.csv").open(encoding="utf-8-sig", newline="") as stream:
            self.assertEqual(next(csv.DictReader(stream))["Grade"], "0.125")
        with zipfile.ZipFile(output / "feedback_files.zip") as archive:
            self.assertTrue(all(".." not in name.split("/") for name in archive.namelist()))
        self.assertEqual(len(list((output / "student_pdfs").glob("*.pdf"))), 2)

    def test_moodle_rejects_ambiguous_or_incomplete_input_before_export(self):
        from handwriting_grader.moodle import export_moodle

        root = self.run_grading()
        self.fill_review(root / "review.xlsx")
        approve_grading(self.config, self.root, self.exam)
        self.assertEqual(main(["report", "--exam", str(self.exam)]), 0)
        worksheet = self.root / "worksheet.csv"
        participants = self.root / "participants.csv"
        for contents, error in (
            ("ID number,Identifier\n001,Participant 1\n", "Grade"),
            ("ID number,Identifier,Grade\n001,,\n", "no participant identifier"),
            ("ID number,Identifier,Grade\n001,Participant 1,\n002,Participant 1,\n", "duplicate"),
            ("ID number,Identifier,Grade\n001,Participant 1,\n001,Participant 2,\n", "duplicate"),
        ):
            worksheet.write_text(contents, encoding="utf-8")
            with self.subTest(contents=contents), self.assertRaisesRegex(ValueError, error):
                export_moodle(self.config, self.root, self.exam, worksheet=worksheet)
            self.assertFalse((root.parent / "moodle").exists())
        for contents, error in (
            ("Name,Email address\nOne,one@example.com\n", "ID and email"),
            ("ID,EMAIL\n001,one@example.com\n001,other@example.com\n", "duplicate"),
        ):
            participants.write_text(contents, encoding="utf-8")
            with self.subTest(contents=contents), self.assertRaisesRegex(ValueError, error):
                export_moodle(self.config, self.root, self.exam, participants=participants)
            self.assertFalse((root.parent / "moodle").exists())

    def test_report_paths_include_safe_unicode_identity_and_remain_unique(self):
        from handwriting_grader.rubric import question_key

        ids = ["00/1", "00:1", "003"]
        name = "Zo\u00eb \u674e\u5c0f\u660e / .."
        roster = {
            sid: {"name": name if index < 2 else "\u674e" * 100, "class": "A"}
            for index, sid in enumerate(ids)
        }
        identities = dict(enumerate(ids))
        results = {"marks": [{"script_index": index, "question": "Q1"} for index in identities]}
        marks = {(index, question_key("Q1")): 1 for index in identities}
        rows, _ = report_rows((None, None, results, [{"question_number": "Q1"}], roster, identities, marks))
        self.assertEqual(rows[0]["pdf"], "pdfs/00_1_Zo\u00eb_\u674e\u5c0f\u660e_script-00001.pdf")
        self.assertEqual(rows[1]["pdf"], "pdfs/00_1_Zo\u00eb_\u674e\u5c0f\u660e_script-00002.pdf")
        self.assertEqual(len({row["pdf"].casefold() for row in rows}), 3)
        for row in rows:
            path = Path(row["pdf"])
            self.assertEqual(path.parent, Path("pdfs"))
            self.assertLessEqual(len(path.name.encode("utf-8")), 255)
            self.assertEqual(row["name"], roster[row["id"]]["name"])

    def test_stale_review_cannot_generate_reports(self):
        root = self.run_grading()
        self.fill_review(root / "review.xlsx")
        approve_grading(self.config, self.root, self.exam)
        self.fill_review(root / "review.xlsx", flagged_override=2)
        self.assertEqual(main(["report", "--exam", str(self.exam)]), 1)
        self.assertFalse((root.parent / "reports").exists())

    def test_analytics_uses_only_approved_reviewed_scores(self):
        root = self.run_grading()
        self.fill_review(root / "review.xlsx", flagged_override=2)
        self.assertEqual(main(["analytics", "--exam", str(self.exam)]), 1)
        self.assertFalse((root.parent / "analytics").exists())
        approve_grading(self.config, self.root, self.exam)
        values = []
        boxplot = Axes.boxplot

        def capture(axis, data, **kwargs):
            values.append(data)
            return boxplot(axis, data, **kwargs)

        with patch.object(Axes, "boxplot", autospec=True, side_effect=capture):
            self.assertEqual(main(["analytics", "--exam", str(self.exam)]), 0)
        self.assertEqual(values, [[[2, 1]]])
        output = root.parent / "analytics"
        book = load_workbook(output / "statistics.xlsx", read_only=True)
        try:
            overall = list(book["Overall"].values)[1]
            self.assertEqual(overall[:3], (2, 1.5, 1.5))
            distribution = list(book["Distribution"].values)
            self.assertEqual(distribution[6][1], 1)
            self.assertEqual(distribution[10][1], 1)
            self.assertEqual(overall[6], 2)
            self.assertIsNone(overall[9])
            question = list(book["Questions"].values)[1]
            self.assertEqual((question[0], question[2], question[7], question[8]), ("Q1", 1.5, 2, 75))
            self.assertEqual(list(book["Classes"].values)[1][:3], ("A", 2, 1.5))
        finally:
            book.close()
        book = load_workbook(output / "statistics.xlsx")
        try:
            self.assertEqual(len(book["Questions"]._charts), 1)
            self.assertEqual(len(book["Distribution"]._charts), 1)
        finally:
            book.close()
        manifest = json.loads((output / "manifest.json").read_text())
        self.assertTrue(manifest["completed"])
        chart = manifest["question_boxplots"][0]
        self.assertEqual(chart["sha256"], file_hash(output / chart["path"]))
        with Image.open(output / chart["path"]) as image:
            self.assertEqual(image.format, "PNG")
            self.assertGreater(image.width, 100)
        self.assertEqual(main(["analytics", "--exam", str(self.exam)]), 1)

    def test_question_boxplots_handle_single_student_and_multiple_pages(self):
        questions = [{"question_number": f"Q{i}"} for i in range(21)]
        rows = [{"marks": list(range(21))}]
        paths = question_boxplots(self.root, rows, questions)
        self.assertEqual(paths, ["question-boxplots-001.png", "question-boxplots-002.png"])
        for path in paths:
            with Image.open(self.root / path) as image:
                self.assertEqual(image.format, "PNG")
                image.verify()

    def test_question_pass_thresholds_are_explicit_and_unambiguous(self):
        questions = [{"question_number": "Q1", "marks": 2}, {"question_number": "Q2", "marks": 3}]
        self.assertEqual(question_passing_policy({}, questions), ({}, None))
        config = {"reporting": {"question_pass_marks": {"Q1": 1.0}, "question_passing_includes_equal": True}}
        self.assertEqual(question_passing_policy(config, questions), ({"1": 1.0}, True))
        for invalid in (
            {"question_pass_marks": {"Q1": 1}},
            {"question_pass_marks": {"Q3": 1}, "question_passing_includes_equal": True},
            {"question_pass_marks": {"Q1": 3}, "question_passing_includes_equal": True},
            {"question_pass_marks": {"Q1": 1, "1": 1}, "question_passing_includes_equal": True},
        ):
            with self.assertRaises(ValueError):
                question_passing_policy({"reporting": invalid}, questions)

    def test_question_pass_rates_use_approved_marks_and_explicit_equality(self):
        self.config["reporting"] = {"question_pass_marks": {"Q1": 1},
                                    "question_passing_includes_equal": False}
        self.config["exam"]["output_dir"] = "policy-output"
        self.exam.write_text(yaml.safe_dump(self.config))
        import_rubric(self.config, self.root, self.exam)
        approve_rubric(self.config, self.root, self.exam)
        regions = prepare_regions(self.config, self.root, 2)
        _, manifest = verify_run(self.config, self.root, self.exam)
        draft = json.loads((self.root / "output" / "regions" / "draft.json").read_text())
        atomic_json(regions / "draft.json", draft)
        atomic_json(regions / "annotations.json", draft["annotations"])
        atomic_json(regions / "approval.json", {
            "annotations_sha256": file_hash(regions / "annotations.json"),
            "config_sha256": manifest["config_sha256"], "pdf_sha256": manifest["pdf_sha256"],
            "revision": draft["revision"],
        })
        prepare_scan_marker_fixture(self, self.config, self.root)
        root = self.run_grading()
        self.fill_review(root / "review.xlsx", flagged_override=2)
        approve_grading(self.config, self.root, self.exam)
        self.assertEqual(main(["analytics", "--exam", str(self.exam)]), 0)
        book = load_workbook(root.parent / "analytics" / "statistics.xlsx", read_only=True)
        try:
            question = list(book["Questions"].values)[1]
            self.assertEqual(question[9:], (1, False, 1, 50))
        finally:
            book.close()

    def test_analysis_cache_reuses_reviewed_inputs(self):
        root = self.run_grading()
        self.fill_review(root / "review.xlsx")
        approve_grading(self.config, self.root, self.exam)
        model = self.root / "analysis-models.yaml"
        model.write_text(yaml.safe_dump({
            "azure_openai": {}, "models": {"analytics": "gpt-5.4"},
            "caching": {"enabled": True, "scope": "shared", "directory": "shared",
                        "agents": {"analytics": True}},
        }))

        class FakeAnalyst:
            calls = []

            def __init__(self, *args):
                pass

            def __enter__(self):
                return self

            def __exit__(self, *args):
                pass

            def analyze(self, task, data):
                self.calls.append((task, data))
                return "Feedback"

        output = create_analysis(self.config, self.root, self.exam, model, "https://test.openai.azure.com", "v1",
                                 provider_factory=FakeAnalyst)
        calls = len(FakeAnalyst.calls)
        self.assertGreater(calls, 0)
        output.rename(root.parent / "previous-analysis")
        create_analysis(self.config, self.root, self.exam, model, "https://test.openai.azure.com", "v1",
                        provider_factory=FakeAnalyst)
        self.assertEqual(len(FakeAnalyst.calls), calls)

    def test_sampling_and_explicit_passing_policy(self):
        rows = [{"script_index": i, "total": i} for i in range(10)]
        selected = sample_rows(rows, 3)
        self.assertEqual([row["total"] for row in selected], [9, 8, 7, 6, 5, 4, 2, 1, 0])
        self.assertEqual(sample_rows(rows[:2], 3), [])
        questions = [{"marks": 10}]
        self.assertIsNone(passing_policy({}, questions))
        self.assertEqual(passing_policy({"reporting": {"pass_mark": 5, "passing_includes_equal": True}}, questions),
                         (5, True))
        self.assertEqual([row["total"] for row in passing_rows(rows, 5, True)], [5, 6, 7, 8, 9])
        self.assertEqual([row["total"] for row in passing_rows(rows, 5, False)], [6, 7, 8, 9])
        with self.assertRaisesRegex(ValueError, "pass_mark"):
            passing_policy({"reporting": {"pass_mark": 5}}, questions)

    def test_report_text_is_not_written_as_formulas(self):
        rows = [{"script_index": 0, "id": "=1+1", "name": "=2+2", "class": "A",
                 "marks": [1], "total": 1, "pdf": "pdfs/script-00001.pdf"}]
        questions = [{"question_number": "=Q", "marks": 2}]
        baselines = {(0, "=Q"): {"answer": "=3+3", "reasoning": "=4+4",
                                 "moderator_flag": False, "moderator_note": ""}}
        write_workbooks(self.root, rows, baselines, questions)
        workbook = load_workbook(self.root / "details_score_report.xlsx", data_only=False)
        try:
            for sheet, cell in [("Marks", "D1"), ("Marks", "A2"), ("Answers", "D2"),
                                ("Reasoning", "D2")]:
                self.assertEqual(workbook[sheet][cell].data_type, "s")
        finally:
            workbook.close()

    def test_azure_sdk_grading_requests_against_fake_service(self):
        from openai import OpenAI
        from handwriting_grader.azure_ai import AzureClient
        from azure_test_support import responses_body, manual_test_prices

        self.models.write_text(yaml.safe_dump(manual_test_prices(yaml.safe_load(self.models.read_text()))))

        calls = []

        class FakeAzure(BaseHTTPRequestHandler):
            def log_message(self, format, *args):
                pass

            def do_POST(self):
                request = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                calls.append((self.path, request))
                req_dump = json.dumps(request)
                schema_name = request.get("text", {}).get("format", {}).get("name")
                if schema_name == "ModerationResponse":
                    text = json.dumps({"items": [
                        {"script_index": i, "moderated_mark": 1, "flag": False, "note": ""}
                        for i in range(2)
                    ]})
                elif schema_name == "MetadataBatchResponse":
                    text = json.dumps({"students": [
                        {"script_index": i, "id_ocr": f"00{i + 1}", "class_ocr": "A", "name_ocr": "Example"}
                        for i in range(2)
                    ]})
                elif "marking" in req_dump.lower():
                    text = json.dumps({"answer": "Example answer", "mark": 1, "similarity_score": 0.5, "reasoning": "Example"})
                else:
                    text = "Example"
                body = responses_body(text)
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        service = ThreadingHTTPServer(("127.0.0.1", 0), FakeAzure)
        thread = threading.Thread(target=service.serve_forever, daemon=True)
        thread.start()
        try:
            def local_client(**kwargs):
                sdk = OpenAI(base_url=f"http://127.0.0.1:{service.server_port}/v1/",
                             api_key="test-only", max_retries=0)
                return AzureClient(**kwargs, client=sdk)

            with patch("handwriting_grader.grading.AzureClient", side_effect=local_client):
                self.assertEqual(main([
                    "grade", "--exam", str(self.exam), "--model-config", str(self.models),
                    "--endpoint", "https://test.openai.azure.com", "--api-version", "v1",
                    "--mode", "item", "--confirm-cost",
                ]), 0)
                root = self.root / "output" / "grading"
            results = json.loads((root / "results.json").read_text())
            self.assertTrue(results["completed"])
            self.assertTrue(all(not row["grading_failed"] for row in results["marks"]))
            self.assertEqual(len(calls), 4)
            self.assertTrue(all(script["name_ocr"] == "Example" for script in results["scripts"]))
            image_request = calls[0][1]
            self.assertTrue(any(part["type"] == "input_image" for content in image_request["input"]
                                for part in content["content"]))
            grade_request = next(body for _, body in calls if body.get("text", {}).get("format", {}).get("name") == "GradeResponse")
            self.assertEqual(grade_request["text"]["format"]["type"], "json_schema")
            self.assertIn("schema", grade_request["text"]["format"])
        finally:
            service.shutdown()
            thread.join(timeout=5)
            service.server_close()

    def prepare_email(self):
        root = self.run_grading()
        self.fill_review(root / "review.xlsx")
        approve_grading(self.config, self.root, self.exam)
        self.assertEqual(main(["report", "--exam", str(self.exam)]), 0)
        settings = self.root / "email-settings.yaml"
        settings.write_text(yaml.safe_dump({
            "sender": "teacher@example.test", "smtp_host": "smtp.example.test", "smtp_port": 587,
            "smtp_username": "teacher", "subject": "{exam} result",
            "body": "Dear {name}, your score is {marks}.",
        }))
        recipients = self.root / "recipients.csv"
        recipients.write_text("ID,EMAIL\n001,one@example.test\n002,two@example.test\n")
        return root, settings, recipients

    def test_email_preview_approval_and_single_send(self):
        root, settings, recipients = self.prepare_email()
        preview = ["preview-email", "--exam", str(self.exam), "--settings", str(settings),
                   "--recipients", str(recipients)]
        approve = ["approve-email", "--exam", str(self.exam)]
        send = ["send-email", "--exam", str(self.exam)]
        with patch("handwriting_grader.distribution.smtplib.SMTP") as smtp, \
             patch.dict(os.environ, {"HANDWRITING_SMTP_PASSWORD": "fake-secret"}):
            server = smtp.return_value.__enter__.return_value
            server.sendmail.return_value = {}
            self.assertEqual(main(preview), 0)
            self.assertEqual(main(approve), 1)
            self.assertEqual(main(send), 1)
            self.assertEqual(main(send + ["--confirm-send"]), 1)
            smtp.assert_not_called()
            self.assertEqual(main(approve + ["--confirm-reviewed"]), 0)
            self.assertEqual(main(send + ["--confirm-send"]), 0)
            self.assertEqual(server.sendmail.call_count, 2)
            self.assertEqual(server.sendmail.call_args_list[0].args[1], ["one@example.test"])
            self.assertIn(b"application/pdf", server.sendmail.call_args_list[0].args[2])
            self.assertIn(b"001_One_script-00001.pdf", server.sendmail.call_args_list[0].args[2])
            self.assertEqual(main(send + ["--confirm-send"]), 1)
            self.assertEqual(server.sendmail.call_count, 2)
        delivery = json.loads((root.parent / "email" / "delivery.json").read_text())
        self.assertEqual(delivery["status"], "completed")
        self.assertEqual(len(delivery["sent"]), 2)

    def test_legacy_report_paths_remain_usable_and_integrity_checked(self):
        from handwriting_grader.distribution import approved_report
        from handwriting_grader.moodle import export_moodle

        root, settings, recipients = self.prepare_email()
        _, rows, reports = approved_report(self.config, self.root, self.exam)
        manifest = json.loads((reports / "manifest.json").read_text())
        hashes = {}
        for row in rows:
            legacy = f"pdfs/script-{row['script_index'] + 1:05d}.pdf"
            (reports / row["pdf"]).rename(reports / legacy)
            hashes[legacy] = manifest["script_pdf_sha256"][row["pdf"]]
        manifest.update(version=1, script_pdf_sha256=hashes)
        atomic_json(reports / "manifest.json", manifest)
        _, legacy_rows, _ = approved_report(self.config, self.root, self.exam)
        self.assertEqual(legacy_rows[0]["pdf"], "pdfs/script-00001.pdf")
        self.assertEqual(main(["preview-email", "--exam", str(self.exam), "--settings", str(settings),
                               "--recipients", str(recipients)]), 0)
        export_moodle(self.config, self.root, self.exam)
        self.assertEqual(
            (root.parent / "moodle" / "student_pdfs" / "001_One.pdf").read_bytes(),
            (reports / "pdfs" / "script-00001.pdf").read_bytes(),
        )
        (reports / "pdfs" / "script-00001.pdf").write_bytes(b"changed")
        with self.assertRaisesRegex(ValueError, "changed"):
            approved_report(self.config, self.root, self.exam)

    def test_email_refuses_changed_recipients_or_attachment(self):
        root, settings, recipients = self.prepare_email()
        self.assertEqual(main(["preview-email", "--exam", str(self.exam), "--settings", str(settings),
                               "--recipients", str(recipients)]), 0)
        recipients.write_text("ID,EMAIL\n001,wrong@example.test\n002,two@example.test\n")
        self.assertEqual(main(["approve-email", "--exam", str(self.exam), "--confirm-reviewed"]), 1)
        self.assertFalse((root.parent / "email" / "approval.json").exists())
        recipients.write_text("ID,EMAIL\n001,one@example.test\n002,two@example.test\n")
        (root.parent / "reports" / "pdfs" / "001_One_script-00001.pdf").write_bytes(b"changed")
        self.assertEqual(main(["approve-email", "--exam", str(self.exam), "--confirm-reviewed"]), 1)

    def test_email_delivery_failure_is_not_retried_automatically(self):
        root, settings, recipients = self.prepare_email()
        self.assertEqual(main(["preview-email", "--exam", str(self.exam), "--settings", str(settings),
                               "--recipients", str(recipients)]), 0)
        self.assertEqual(main(["approve-email", "--exam", str(self.exam), "--confirm-reviewed"]), 0)
        with patch("handwriting_grader.distribution.smtplib.SMTP") as smtp, \
             patch.dict(os.environ, {"HANDWRITING_SMTP_PASSWORD": "fake-secret"}):
            server = smtp.return_value.__enter__.return_value
            server.sendmail.side_effect = OSError("ambiguous response")
            args = ["send-email", "--exam", str(self.exam), "--confirm-send"]
            self.assertEqual(main(args), 1)
            self.assertEqual(main(args), 1)
            self.assertEqual(server.sendmail.call_count, 1)
        journal = json.loads((root.parent / "email" / "delivery.json").read_text())
        self.assertEqual(journal["in_flight"], "message-00001.eml")

    def test_ai_analysis_requires_review_and_generates_office_reports(self):
        root = self.run_grading()
        self.fill_review(root / "review.xlsx")
        approve_grading(self.config, self.root, self.exam)
        settings = yaml.safe_load(self.models.read_text())
        settings["models"]["analytics"] = "gpt-5.4"
        # Model configuration is bound to the grading run, so provide separate settings for analytics.
        analytics_models = self.root / "analytics-models.yaml"
        analytics_models.write_text(yaml.safe_dump(settings))
        arguments = ["ai-analysis", "--exam", str(self.exam), "--model-config", str(analytics_models),
                     "--endpoint", "https://test.openai.azure.com", "--api-version", "v1"]
        with patch("handwriting_grader.advanced.create_analysis") as create:
            self.assertEqual(main(arguments), 1)
            create.assert_not_called()

        class FakeAnalyst:
            calls = []

            def __init__(self, model, endpoint, api_version):
                pass

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                pass

            def analyze(self, task, data):
                self.calls.append((task, data))
                return "Reviewed feedback."

        output = create_analysis(self.config, self.root, self.exam, analytics_models, "https://test.openai.azure.com", "v1",
                                 provider_factory=FakeAnalyst)
        self.assertEqual(len(FakeAnalyst.calls), 4)
        self.assertEqual(main(["report", "--exam", str(self.exam)]), 0)
        email_settings = self.root / "email-settings.yaml"
        email_settings.write_text(yaml.safe_dump({
            "sender": "teacher@example.test", "smtp_host": "smtp.example.test", "smtp_port": 587,
            "smtp_username": "teacher", "subject": "{exam} result", "body": "Hello {name}\n{feedback}",
        }))
        recipients = self.root / "recipients.csv"
        recipients.write_text("ID,EMAIL\n001,one@example.test\n002,two@example.test\n")
        preview = ["preview-email", "--exam", str(self.exam), "--settings", str(email_settings),
                   "--recipients", str(recipients)]
        self.assertEqual(main(preview), 1)
        self.assertEqual(main(["approve-analysis", "--exam", str(self.exam), "--confirm-reviewed"]), 1)
        book = load_workbook(output / "review.xlsx")
        for sheet in ("Students", "Questions", "Class"):
            for row in book[sheet].iter_rows(min_row=2):
                row[-1].value = "yes"
        book.save(output / "review.xlsx")
        book.close()
        self.assertEqual(main(["approve-analysis", "--exam", str(self.exam), "--confirm-reviewed"]), 0)
        self.assertEqual(main(preview), 0)
        mail = json.loads((root.parent / "email" / "preview.json").read_text())
        self.assertIn("Reviewed feedback.", mail["messages"][0]["body"])
        self.assertEqual(main(["approve-email", "--exam", str(self.exam), "--confirm-reviewed"]), 0)
        self.assertEqual(main(["advanced-report", "--exam", str(self.exam)]), 0)
        report = output / "reports"
        self.assertTrue(any("Reviewed feedback." in p.text for p in Document(report / "teacher-report.docx").paragraphs))
        self.assertEqual(len(Presentation(report / "class-presentation.pptx").slides), 3)
        self.assertTrue(json.loads((report / "manifest.json").read_text())["completed"])
        book = load_workbook(output / "review.xlsx")
        book["Class"]["A2"] = "Changed"
        book.save(output / "review.xlsx")
        book.close()
        self.assertEqual(main(["advanced-report", "--exam", str(self.exam)]), 1)
        self.assertEqual(main(["send-email", "--exam", str(self.exam), "--confirm-send"]), 1)

    def test_azure_sdk_ai_analysis_against_local_fake_service(self):
        from openai import OpenAI
        from handwriting_grader.azure_ai import AzureClient
        from azure_test_support import responses_body, manual_test_prices

        calls = []

        class FakeAzure(BaseHTTPRequestHandler):
            def log_message(self, format, *args):
                pass

            def do_POST(self):
                calls.append(json.loads(self.rfile.read(int(self.headers["Content-Length"]))))
                body = responses_body("Feedback.")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        root = self.run_grading()
        self.fill_review(root / "review.xlsx")
        approve_grading(self.config, self.root, self.exam)
        settings = yaml.safe_load(self.models.read_text())
        settings["models"]["analytics"] = "school-analysis"
        settings["models"]["grading"] = "school-chat"
        settings["deployment_models"] = {"school-analysis": "gpt-5.4", "school-chat": "gpt-5.4-mini"}
        settings["pricing"] = {
            name: {"input": 2, "output": 8} for name in ("school-analysis", "school-chat")
        }
        model = self.root / "analytics-models.yaml"
        model.write_text(yaml.safe_dump(manual_test_prices(settings)))
        service = ThreadingHTTPServer(("127.0.0.1", 0), FakeAzure)
        thread = threading.Thread(target=service.serve_forever, daemon=True)
        thread.start()
        try:
            def local_client(**kwargs):
                sdk = OpenAI(base_url=f"http://127.0.0.1:{service.server_port}/v1/",
                             api_key="test-only", max_retries=0)
                return AzureClient(**kwargs, client=sdk)

            with patch("handwriting_grader.advanced.AzureClient", side_effect=local_client):
                self.assertEqual(main([
                    "ai-analysis", "--exam", str(self.exam), "--model-config", str(model),
                    "--endpoint", "https://test.openai.azure.com", "--api-version", "v1", "--confirm-cost",
                ]), 0)
            output = root.parent / "ai-analysis"
            self.assertEqual(len(calls), 4)
            self.assertEqual(sorted(call["model"] for call in calls),
                             ["school-analysis", "school-analysis", "school-chat", "school-chat"])
            self.assertIn("Example answer", json.dumps(calls[0]))
            self.assertTrue((output / "review.xlsx").is_file())
            traces = [json.loads(line) for line in (output / "telemetry" / "azure_usage.jsonl").read_text().splitlines()]
            self.assertEqual(len(traces), 4)
            self.assertTrue(all(trace["cost_known"] and trace["cost_usd"] == 0.000056 for trace in traces))
            self.assertAlmostEqual(json.loads((output / "cost_summary.json").read_text())["total_cost_usd"], 0.000224)
        finally:
            service.shutdown()
            thread.join(timeout=5)
            service.server_close()


if __name__ == "__main__":
    unittest.main()
