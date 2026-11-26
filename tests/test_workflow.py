import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from handwriting_grader.workflow import run_batch_recovery_workflow, run_grading_workflow


class TestMicrosoftGradingWorkflow(unittest.TestCase):
    def test_batch_recovery_workflow_validates_and_requires_review(self):
        recovery = Mock(return_value={"recovered": 1, "history": Path("history")})
        with patch("handwriting_grader.batch_recovery.inspect_batch_recovery",
                   return_value={"revision": "current"}), \
             patch("handwriting_grader.batch_recovery.recover_question_batches", recovery):
            with self.assertRaisesRegex(ValueError, "changed after preview"):
                run_batch_recovery_workflow({}, Path("."), Path("exam.yaml"), "Q1", "stale", 3)
            recovery.assert_not_called()
            result = run_batch_recovery_workflow({}, Path("."), Path("exam.yaml"), "Q1", "current", 3)
        recovery.assert_called_once()
        self.assertEqual(result, {"recovered": 1, "history": "history"})

    def test_missing_human_approval_stops_before_grading(self):
        grade = Mock()
        with patch("handwriting_grader.workflow.approved_inputs", side_effect=ValueError("approval missing")):
            with self.assertRaisesRegex(ValueError, "approval missing"):
                run_grading_workflow({}, Path("."), Path("exam.yaml"), Path("models.yaml"),
                                     "https://school.openai.azure.com", "v1", {}, grade_function=grade)
        grade.assert_not_called()

    def test_workflow_runs_grading_without_granting_score_approval(self):
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp) / "grading"
            output.mkdir()
            grade = Mock(return_value=output)
            with patch("handwriting_grader.workflow.approved_inputs"):
                result = run_grading_workflow({}, Path(temp), Path(temp) / "exam.yaml",
                                              Path(temp) / "models.yaml",
                                              "https://school.openai.azure.com", "v1", {},
                                              grade_function=grade, continue_on_image_policy_block=True)
            self.assertEqual(result, output)
            grade.assert_called_once()
            self.assertTrue(grade.call_args.kwargs["continue_on_image_policy_block"])
            self.assertFalse((output / "approval.json").exists())
