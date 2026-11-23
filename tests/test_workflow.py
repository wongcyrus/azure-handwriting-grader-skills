import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from handwriting_grader.workflow import run_grading_workflow


class TestMicrosoftGradingWorkflow(unittest.TestCase):
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
                                              grade_function=grade)
            self.assertEqual(result, output)
            grade.assert_called_once()
            self.assertFalse((output / "approval.json").exists())
