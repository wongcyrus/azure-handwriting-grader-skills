"""Unit tests for multimodal batch grading and structured output mode."""

import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from PIL import Image, ImageDraw
from openpyxl import load_workbook
import httpx2
from openai import BadRequestError

from handwriting_grader.grading import (
    MetadataBatchResponse,
    QuestionBatchGradeResponse,
    StudentMetadataItem,
    StudentBatchGradeItem,
    batch_extract_metadata,
    continue_grading,
    export_failed_review,
    inspect_failed_question_batches,
    retry_failed_question_batches,
)
from handwriting_grader.regions import atomic_json, file_hash
from handwriting_grader.telemetry import TelemetryTracker


class FakeBatchProvider:
    def __init__(self, models, endpoint, api_version):
        self.batch_calls = []
        self.item_calls = []

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        pass

    def ocr(self, image, field):
        return f"VAL_{field}"

    def grade_question_batch(self, question, script_items):
        self.batch_calls.append((question["question_number"], len(script_items)))
        return {
            item["script_index"]: {
                "script_index": item["script_index"],
                "answer": f"Answer for script {item['script_index']}",
                "mark": float(question["marks"]),
                "similarity_score": 0.95,
                "reasoning": f"Good answer for script {item['script_index']}",
                "moderator_flag": item["script_index"] == 1,
                "moderator_note": "Review script 1" if item["script_index"] == 1 else "",
            }
            for item in script_items
        }

    def grade(self, question, answer="", image=None):
        self.item_calls.append(question["question_number"])
        return {"answer": "Item answer", "mark": 1.0, "similarity_score": 0.5, "reasoning": "Item reasoning"}

    def moderate(self, question, entries):
        return {
            e["script_index"]: {
                "script_index": e["script_index"],
                "moderated_mark": e["mark"],
                "flag": False,
                "note": "",
            }
            for e in entries
        }


class FakeItemOnlyProvider:
    def __init__(self, models, endpoint, api_version):
        self.item_calls = []
        self.mod_calls = []

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        pass

    def ocr(self, image, field):
        return f"VAL_{field}"

    def grade(self, question, answer="", image=None):
        self.item_calls.append(question["question_number"])
        return {"answer": "Item answer", "mark": 1.0, "similarity_score": 0.5, "reasoning": "Item reasoning"}

    def moderate(self, question, entries):
        self.mod_calls.append(question["question_number"])
        return {
            e["script_index"]: {
                "script_index": e["script_index"],
                "moderated_mark": e["mark"],
                "flag": False,
                "note": "",
            }
            for e in entries
        }


class TestBatchGrading(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.images_dir = self.root / "images"
        self.images_dir.mkdir(parents=True)

        # Create 2 scripts (1 page each)
        for i in range(2):
            img = Image.new("RGB", (300, 300), "white")
            draw = ImageDraw.Draw(img)
            # Add handwriting inside Q1.1 (y: 50..100) and Q1.2 (y: 110..160)
            draw.line([(25, 75), (85, 75)], fill="black", width=5)
            draw.line([(25, 135), (85, 135)], fill="black", width=5)
            img.save(self.images_dir / f"{i}.jpg", "JPEG")

        self.questions = [
            {"question_number": "1.1", "question_text": "Q1", "marking_scheme": "Criteria 1", "marks": 2},
            {"question_number": "1.2", "question_text": "Q2", "marking_scheme": "Criteria 2", "marks": 3},
        ]
        self.boxes = {
            "ID": (0, {"x": 10, "y": 10, "width": 50, "height": 30, "label": "ID"}),
            "CLASS": (0, {"x": 70, "y": 10, "width": 50, "height": 30, "label": "CLASS"}),
            "NAME": (0, {"x": 130, "y": 10, "width": 50, "height": 30, "label": "NAME"}),
            "1.1": (0, {"x": 10, "y": 50, "width": 100, "height": 50, "label": "1.1"}),
            "1.2": (0, {"x": 10, "y": 110, "width": 100, "height": 50, "label": "1.2"}),
        }
        self.summary = {"students": 2}
        self.stride = 1
        self.models = {"ocr": "flash", "grading": "flash", "moderation": "argon", "batch_grading": "argon"}
        self.metadata_fields = ["ID", "CLASS", "NAME"]

    def test_metadata_batches_respect_image_limit_and_cover_all_scripts(self):
        class MetadataProvider:
            def __init__(self):
                self.batch_sizes = []

            def ocr_metadata_batch(self, items, **kwargs):
                self.batch_sizes.append(sum(len(item["crops"]) for item in items))
                return MetadataBatchResponse(students=[
                    StudentMetadataItem(script_index=item["script_index"])
                    for item in items
                ])

        provider = MetadataProvider()
        with patch("handwriting_grader.grading.crop_image", return_value=b"image"):
            result = batch_extract_metadata(
                provider, list(range(58)), self.metadata_fields, self.boxes, 2,
                self.images_dir, tracker=TelemetryTracker(),
            )
        self.assertEqual(provider.batch_sizes, [48, 48, 48, 30])
        self.assertEqual(set(result), set(range(58)))

    def test_metadata_batch_failure_surfaces_without_extra_ocr_requests(self):
        class FailingProvider:
            def ocr_metadata_batch(self, items, **kwargs):
                raise ValueError("simulated provider failure")

            def ocr(self, *args, **kwargs):
                raise AssertionError("Unexpected fallback request")

        with patch("handwriting_grader.grading.crop_image", return_value=b"image"):
            with self.assertRaisesRegex(RuntimeError, "ValueError.*simulated provider failure"):
                batch_extract_metadata(
                    FailingProvider(), [0], self.metadata_fields, self.boxes, 2,
                    self.images_dir, tracker=TelemetryTracker(),
                )

    def test_metadata_rejects_missing_or_duplicate_script_results(self):
        class IncompleteProvider:
            def ocr_metadata_batch(self, items, **kwargs):
                return MetadataBatchResponse(students=[
                    StudentMetadataItem(script_index=items[0]["script_index"]),
                    StudentMetadataItem(script_index=items[0]["script_index"]),
                ])

        with patch("handwriting_grader.grading.crop_image", return_value=b"image"):
            with self.assertRaisesRegex(ValueError, "exactly once"):
                batch_extract_metadata(
                    IncompleteProvider(), [0, 1], self.metadata_fields, self.boxes,
                    2, self.images_dir,
                )

    def test_batch_mode_grades_all_questions_and_sets_fields(self):
        results = {"version": 1, "checkpoint_version": 1, "completed": False, "scripts": [], "marks": [], "moderated_questions": []}
        atomic_json(self.root / "results.json", results)

        provider_inst = None
        def provider_factory(models, endpoint, api_version):
            nonlocal provider_inst
            provider_inst = FakeBatchProvider(models, endpoint, api_version)
            return provider_inst

        continue_grading(
            self.root, results, self.questions, self.boxes, self.summary, self.stride,
            self.models, "endpoint", "api_version", provider_factory,
            [], self.root / "cache", self.metadata_fields, lambda: None,
            mode="batch", batch_concurrency=2,
        )

        saved = json.loads((self.root / "results.json").read_text())
        self.assertEqual(len(saved["scripts"]), 2)
        self.assertEqual(len(saved["marks"]), 4)  # 2 questions * 2 scripts
        self.assertEqual(len(saved["moderated_questions"]), 2)

        # Batch provider was called once per question (2 questions = 2 batch calls)
        self.assertEqual(len(provider_inst.batch_calls), 2)
        self.assertEqual(len(provider_inst.item_calls), 0)

        # Verify mark contents
        m0 = next(m for m in saved["marks"] if m["question"] == "1.1" and m["script_index"] == 0)
        self.assertEqual(m0["raw_mark"], 2.0)
        self.assertEqual(m0["moderated_mark"], 2.0)
        self.assertFalse(m0["moderator_flag"])
        self.assertFalse(m0["grading_failed"])

        m1 = next(m for m in saved["marks"] if m["question"] == "1.1" and m["script_index"] == 1)
        self.assertTrue(m1["moderator_flag"])
        self.assertEqual(m1["moderator_note"], "Review script 1")

    def test_batch_mode_handles_blank_cell_locally_without_ai(self):
        # Make script 1's question 1.1 box pure white
        white_img = Image.new("RGB", (300, 300), "white")
        white_img.save(self.images_dir / "1.jpg", "JPEG")

        results = {"version": 1, "checkpoint_version": 1, "completed": False, "scripts": [], "marks": [], "moderated_questions": []}
        atomic_json(self.root / "results.json", results)

        provider_inst = None
        def provider_factory(models, endpoint, api_version):
            nonlocal provider_inst
            provider_inst = FakeBatchProvider(models, endpoint, api_version)
            return provider_inst

        continue_grading(
            self.root, results, self.questions, self.boxes, self.summary, self.stride,
            self.models, "endpoint", "api_version", provider_factory,
            [], self.root / "cache", self.metadata_fields, lambda: None,
            mode="batch", batch_concurrency=1,
        )

        saved = json.loads((self.root / "results.json").read_text())
        m1_blank = next(m for m in saved["marks"] if m["question"] == "1.1" and m["script_index"] == 1)
        self.assertEqual(m1_blank["raw_mark"], 0)
        self.assertEqual(m1_blank["moderated_mark"], 0)
        self.assertEqual(m1_blank["reasoning"], "Blank answer (local filter).")
        self.assertFalse(m1_blank["moderator_flag"])

        # Script 0 was non-blank, so batch_calls for Q1.1 had length 1 (script 1 omitted from AI call!)
        q1_batch = next(call for call in provider_inst.batch_calls if call[0] == "1.1")
        self.assertEqual(q1_batch[1], 1)

    def test_batch_failure_preserves_details_and_stops_later_questions(self):
        class FailingBatchProvider(FakeBatchProvider):
            def grade_question_batch(self, question, script_items):
                self.batch_calls.append(question["question_number"])
                raise ValueError("provider diagnostic")

        provider = FailingBatchProvider({}, "endpoint", "v1")
        results = {"version": 1, "checkpoint_version": 1, "completed": False,
                   "scripts": [], "marks": [], "moderated_questions": []}
        atomic_json(self.root / "results.json", results)
        with self.assertRaisesRegex(RuntimeError, r"1\.1.*ValueError.*provider diagnostic"):
            continue_grading(
                self.root, results, self.questions, self.boxes, self.summary, self.stride,
                self.models, "endpoint", "api_version", lambda *args: provider,
                [], self.root / "cache", self.metadata_fields, lambda: None,
                mode="batch", batch_concurrency=1,
            )
        saved = json.loads((self.root / "results.json").read_text())
        self.assertEqual(provider.batch_calls, ["1.1"])
        self.assertFalse(saved["completed"])
        self.assertEqual(len(saved["marks"]), 2)
        self.assertTrue(all(mark["grading_failed"] for mark in saved["marks"]))
        self.assertTrue(all(mark["grading_error_detail"] == "provider diagnostic" for mark in saved["marks"]))

    def test_opt_in_continues_after_image_policy_block_without_retrying(self):
        response = httpx2.Response(400, request=httpx2.Request("POST", "https://example.invalid"))

        class PolicyBlockProvider(FakeBatchProvider):
            def grade_question_batch(self, question, items):
                if question["question_number"] == "1.1":
                    self.batch_calls.append(("1.1", len(items)))
                    raise BadRequestError("Image processing blocked due to content policy violation.",
                                          response=response, body=None)
                return super().grade_question_batch(question, items)

        provider = PolicyBlockProvider({}, "", "")
        results = {"version": 1, "checkpoint_version": 1, "completed": False,
                   "scripts": [], "marks": [], "moderated_questions": []}
        atomic_json(self.root / "results.json", results)
        continue_grading(
            self.root, results, self.questions, self.boxes, self.summary, self.stride,
            self.models, "endpoint", "api_version", lambda *args: provider,
            [], self.root / "cache", self.metadata_fields, lambda: None,
            mode="batch", batch_concurrency=1, continue_on_image_policy_block=True,
        )
        self.assertEqual(provider.batch_calls, [("1.1", 2), ("1.2", 2)])
        blocked = [row for row in results["marks"] if row["question"] == "1.1"]
        self.assertTrue(all(row["grading_failed"] and row["image_policy_block"] for row in blocked))
        self.assertTrue(all(row["raw_mark"] is None and row["moderated_mark"] is None for row in blocked))
        self.assertTrue(all(row["moderator_flag"] and row["moderator_note"] == "image_policy_block" for row in blocked))
        self.assertTrue(all(not row["grading_failed"] for row in results["marks"] if row["question"] == "1.2"))

    def test_image_policy_block_stops_by_default(self):
        response = httpx2.Response(400, request=httpx2.Request("POST", "https://example.invalid"))

        class PolicyBlockProvider(FakeBatchProvider):
            def grade_question_batch(self, question, items):
                self.batch_calls.append(question["question_number"])
                raise BadRequestError("Image processing blocked due to content policy violation.",
                                      response=response, body=None)

        provider = PolicyBlockProvider({}, "", "")
        results = {"version": 1, "checkpoint_version": 1, "completed": False,
                   "scripts": [], "marks": [], "moderated_questions": []}
        atomic_json(self.root / "results.json", results)
        with self.assertRaisesRegex(RuntimeError, "content policy violation"):
            continue_grading(
                self.root, results, self.questions, self.boxes, self.summary, self.stride,
                self.models, "endpoint", "api_version", lambda *args: provider,
                [], self.root / "cache", self.metadata_fields, lambda: None,
                mode="batch", batch_concurrency=1,
            )
        self.assertEqual(provider.batch_calls, ["1.1"])
        self.assertTrue(all(row["grading_failed"] and row["raw_mark"] is None for row in results["marks"]))

    def test_opt_in_still_stops_on_other_bad_requests(self):
        response = httpx2.Response(400, request=httpx2.Request("POST", "https://example.invalid"))

        class OtherBadRequest(FakeBatchProvider):
            def grade_question_batch(self, question, items):
                self.batch_calls.append(question["question_number"])
                raise BadRequestError("Invalid image format.", response=response, body=None)

        provider = OtherBadRequest({}, "", "")
        results = {"version": 1, "checkpoint_version": 1, "completed": False,
                   "scripts": [], "marks": [], "moderated_questions": []}
        atomic_json(self.root / "results.json", results)
        with self.assertRaisesRegex(RuntimeError, "Invalid image format"):
            continue_grading(
                self.root, results, self.questions, self.boxes, self.summary, self.stride,
                self.models, "endpoint", "api_version", lambda *args: provider,
                [], self.root / "cache", self.metadata_fields, lambda: None,
                mode="batch", batch_concurrency=1, continue_on_image_policy_block=True,
            )
        self.assertEqual(provider.batch_calls, ["1.1"])

    def test_opt_in_still_stops_on_other_errors(self):
        class OtherFailure(FakeBatchProvider):
            def grade_question_batch(self, question, items):
                self.batch_calls.append(question["question_number"])
                raise ValueError("response validation failed")

        provider = OtherFailure({}, "", "")
        results = {"version": 1, "checkpoint_version": 1, "completed": False,
                   "scripts": [], "marks": [], "moderated_questions": []}
        atomic_json(self.root / "results.json", results)
        with self.assertRaisesRegex(RuntimeError, "response validation failed"):
            continue_grading(
                self.root, results, self.questions, self.boxes, self.summary, self.stride,
                self.models, "endpoint", "api_version", lambda *args: provider,
                [], self.root / "cache", self.metadata_fields, lambda: None,
                mode="batch", batch_concurrency=1, continue_on_image_policy_block=True,
            )
        self.assertEqual(provider.batch_calls, ["1.1"])

    def test_fallback_to_item_when_provider_lacks_batch_method(self):
        results = {"version": 1, "checkpoint_version": 1, "completed": False, "scripts": [], "marks": [], "moderated_questions": []}
        atomic_json(self.root / "results.json", results)

        provider_inst = None
        def provider_factory(models, endpoint, api_version):
            nonlocal provider_inst
            provider_inst = FakeItemOnlyProvider(models, endpoint, api_version)
            return provider_inst

        continue_grading(
            self.root, results, self.questions, self.boxes, self.summary, self.stride,
            self.models, "endpoint", "api_version", provider_factory,
            [], self.root / "cache", self.metadata_fields, lambda: None,
            mode="batch", batch_concurrency=1,
        )

        saved = json.loads((self.root / "results.json").read_text())
        self.assertEqual(len(saved["marks"]), 4)
        # item provider was called for each script and question
        self.assertEqual(len(provider_inst.item_calls), 4)
        self.assertEqual(len(provider_inst.mod_calls), 2)

    def test_structured_output_schema_validation(self):
        valid_data = {
            "grades": [
                {
                    "script_index": 0,
                    "answer": "Answer 0",
                    "mark": 2.5,
                    "similarity_score": 0.8,
                    "reasoning": "Good",
                    "moderator_flag": False,
                    "moderator_note": "",
                }
            ]
        }
        resp = QuestionBatchGradeResponse.model_validate(valid_data)
        self.assertEqual(len(resp.grades), 1)
        self.assertEqual(resp.grades[0].mark, 2.5)

        # Missing required field
        invalid_data = {"grades": [{"script_index": 0}]}
        with self.assertRaises(Exception):
            QuestionBatchGradeResponse.model_validate(invalid_data)

    def test_failed_question_retry_preserves_checkpoint_and_stops_on_error(self):
        target = self.root / "grading"
        target.mkdir()
        config = {"exam": {"output_dir": str(self.root)}, "layout": {"pages_per_student": 1}}
        manifest = {"grading_mode": "batch", "models": self.models, "endpoint": "endpoint", "api_version": "v1"}
        results = {
            "version": 1, "checkpoint_version": 1, "completed": False,
            "scripts": [{"script_index": 0}, {"script_index": 1}],
            "moderated_questions": ["1.1", "1.2"],
            "marks": [
                {"script_index": si, "question": q["question_number"], "page_image": f"images/{si}.jpg",
                 "raw_mark": None if si == 0 else 1, "grading_failed": si == 0}
                for q in self.questions for si in range(2)
            ],
        }
        atomic_json(target / "results.json", results)

        def verify(*args, **kwargs):
            return target, manifest, json.loads((target / "results.json").read_text()), self.questions

        class FailFirst(FakeBatchProvider):
            def grade_question_batch(self, question, items):
                self.batch_calls.append(question["question_number"])
                raise ValueError("policy blocked")

        provider = FailFirst({}, "", "")
        with patch("handwriting_grader.grade_review.verify_grading_run", side_effect=verify), \
             patch("handwriting_grader.grading.approved_inputs", return_value=(self.questions, None, None, self.boxes)), \
             patch("handwriting_grader.grading.attendance_guard", return_value=lambda: None), \
             patch("handwriting_grader.grading.crop_image", return_value=b"image"):
            info = inspect_failed_question_batches(config, self.root, self.root / "exam.yaml", self.summary)
            self.assertEqual(info["requests"], 2)
            with self.assertRaisesRegex(RuntimeError, r"1\.1.*policy blocked"):
                retry_failed_question_batches(config, self.root, self.root / "exam.yaml", self.summary,
                                              info["checkpoint_hash"], lambda *args: provider)
        self.assertEqual(provider.batch_calls, ["1.1"])
        self.assertEqual(json.loads((target / "results.json").read_text()), results)
        backup = next((target / "retry-history").iterdir())
        self.assertEqual(json.loads((backup / "results.json").read_text()), results)
        self.assertEqual(json.loads((backup / "failure.json").read_text())["question"], "1.1")
        provider = FakeBatchProvider({}, "", "")
        with patch("handwriting_grader.grade_review.verify_grading_run", side_effect=verify), \
             patch("handwriting_grader.grading.approved_inputs", return_value=(self.questions, None, None, self.boxes)), \
             patch("handwriting_grader.grading.attendance_guard", return_value=lambda: None), \
             patch("handwriting_grader.grading.crop_image", return_value=b"image"):
            info = inspect_failed_question_batches(
                config, self.root, self.root / "exam.yaml", self.summary, exclude_questions=["1.1"],
            )
            self.assertEqual(info["requests"], 1)
            retry_failed_question_batches(
                config, self.root, self.root / "exam.yaml", self.summary,
                info["checkpoint_hash"], lambda *args: provider, exclude_questions=["1.1"],
            )
        saved = json.loads((target / "results.json").read_text())
        self.assertEqual(provider.batch_calls, [("1.2", 1)])
        self.assertEqual(saved["marks"][:2], results["marks"][:2])
        self.assertFalse(saved["marks"][2]["grading_failed"])
        self.assertFalse(saved["completed"])

    def test_failed_question_retry_updates_only_failures_without_completing_run(self):
        target = self.root / "grading"
        target.mkdir()
        config = {"exam": {"output_dir": str(self.root)}, "layout": {"pages_per_student": 1}}
        manifest = {"grading_mode": "batch", "models": self.models, "endpoint": "endpoint", "api_version": "v1"}
        results = {
            "version": 1, "checkpoint_version": 1, "completed": False,
            "scripts": [{"script_index": 0}, {"script_index": 1}],
            "moderated_questions": ["1.1"],
            "marks": [
                {"script_index": 0, "question": "1.1", "page_image": "images/0.jpg",
                 "raw_mark": None, "grading_failed": True, "grading_error_detail": "old"},
                {"script_index": 1, "question": "1.1", "page_image": "images/1.jpg",
                 "raw_mark": 1, "grading_failed": False, "answer": "preserve"},
            ],
        }
        atomic_json(target / "results.json", results)

        def verify(*args, **kwargs):
            return target, manifest, json.loads((target / "results.json").read_text()), self.questions

        provider = FakeBatchProvider({}, "", "")
        with patch("handwriting_grader.grade_review.verify_grading_run", side_effect=verify), \
             patch("handwriting_grader.grading.approved_inputs", return_value=(self.questions, None, None, self.boxes)), \
             patch("handwriting_grader.grading.attendance_guard", return_value=lambda: None), \
             patch("handwriting_grader.grading.crop_image", return_value=b"image"):
            retry_failed_question_batches(config, self.root, self.root / "exam.yaml", self.summary,
                                          file_hash(target / "results.json"), lambda *args: provider)
        saved = json.loads((target / "results.json").read_text())
        self.assertEqual(provider.batch_calls, [("1.1", 1)])
        self.assertEqual(provider.item_calls, [])
        self.assertEqual(saved["marks"][1], results["marks"][1])
        self.assertEqual(saved["marks"][0]["raw_mark"], 2.0)
        self.assertFalse(saved["marks"][0]["grading_failed"])
        self.assertNotIn("grading_error_detail", saved["marks"][0])
        self.assertFalse(saved["completed"])

    def test_offline_failed_review_export_is_separate_and_grouped(self):
        target = self.root / "grading"
        target.mkdir()
        config = {"exam": {"output_dir": str(self.root)}, "layout": {"pages_per_student": 1}}
        manifest = {"grading_mode": "batch", "annotations_sha256": "annotations", "rubric_sha256": "rubric"}
        results = {
            "version": 1, "checkpoint_version": 1, "completed": False,
            "scripts": [{"script_index": 0}, {"script_index": 1}],
            "moderated_questions": ["1.1", "1.2"],
            "marks": [
                {"script_index": si, "question": q["question_number"], "page_image": f"images/{si}.jpg",
                 "raw_mark": None if si == 0 else 1, "grading_failed": si == 0}
                for q in reversed(self.questions) for si in range(2)
            ],
        }
        atomic_json(target / "results.json", results)
        digest = file_hash(target / "results.json")

        def verify(*args, **kwargs):
            return target, manifest, json.loads((target / "results.json").read_text()), self.questions

        output = self.root / "manual-review"
        with patch("handwriting_grader.grade_review.verify_grading_run", side_effect=verify), \
             patch("handwriting_grader.grading.approved_inputs", return_value=(self.questions, None, None, self.boxes)), \
             patch("handwriting_grader.grading.crop_image", return_value=b"synthetic crop"):
            export_failed_review(config, self.root, self.root / "exam.yaml", self.summary, output)
            with self.assertRaises(FileExistsError):
                export_failed_review(config, self.root, self.root / "exam.yaml", self.summary, output)
        self.assertEqual(file_hash(target / "results.json"), digest)
        self.assertEqual(len(list((output / "crops").glob("*.png"))), 2)
        workbook = load_workbook(output / "review.xlsx")
        try:
            sheet = workbook["Failed answers"]
            self.assertEqual(sheet["A2"].value, "1.1")
            self.assertEqual(sheet["A3"].value, "1.2")
            self.assertEqual(sheet["D2"].hyperlink.target, "crops\\crop-0001.png")
            self.assertIsNone(sheet["H2"].value)
        finally:
            workbook.close()
        self.assertEqual(json.loads((output / "manifest.json").read_text())["failed_answers"], 2)


if __name__ == "__main__":
    unittest.main()
