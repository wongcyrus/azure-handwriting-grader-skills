from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from handwriting_grader.workflow import run_grading_workflow


order = []


def synthetic_validation(*args):
    order.append("validate")


def grading_stub(*args, **kwargs):
    order.append("grade_stub")
    return draft


with TemporaryDirectory() as directory:
    root = Path(directory)
    draft = root / "draft"
    draft.mkdir()
    with (
        patch("handwriting_grader.workflow.approved_inputs", side_effect=synthetic_validation) as validation,
        patch("handwriting_grader.grading.AzureClient",
              side_effect=AssertionError("Azure clients are forbidden in this offline example")) as azure,
    ):
        output = run_grading_workflow(
            {}, root, root / "synthetic-exam.yaml", root / "synthetic-models.yaml",
            "https://synthetic.openai.azure.com", "v1", {"students": 4},
            grade_function=grading_stub,
        )
        assert order == ["validate", "grade_stub"] and output == draft
        azure.assert_not_called()
        print("Execution order:", " -> ".join(order))
        print("Validation calls:", validation.call_count)
        print("Workflow output:", output.name)
        print("Azure clients constructed:", azure.call_count)
