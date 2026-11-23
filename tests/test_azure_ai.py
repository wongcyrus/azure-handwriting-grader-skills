import json
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from pydantic import BaseModel

from handwriting_grader.azure_ai import (
    AIResponse, AzureClient, GenerationConfig, ImagePart, image_chunks, normalize_usage,
)
from handwriting_grader.grading import (
    AzureGrader, MetadataBatchResponse, QuestionBatchGradeResponse, StudentMetadataItem,
    StudentBatchGradeItem,
)


ENDPOINT = "https://school.openai.azure.com"


class Answer(BaseModel):
    answer: str
    flag: bool = False


class TestAzureTransport(unittest.TestCase):
    def test_structured_vision_uses_explicit_azure_route_and_no_storage(self):
        result = SimpleNamespace(status="completed", output_text='{"answer":"example","flag":false}',
                                 output=[], usage=SimpleNamespace(input_tokens=10, output_tokens=5, total_tokens=15))
        sdk = Mock()
        sdk.responses.create.return_value = result
        client = AzureClient(ENDPOINT, client=sdk)
        response = client.generate_content(
            model="school-grader", contents=["Grade only the answer", ImagePart(b"synthetic", "image/png")],
            config=GenerationConfig(response_schema=Answer, temperature=0),
        )
        request = sdk.responses.create.call_args.kwargs
        self.assertFalse(request["store"])
        self.assertEqual(request["model"], "school-grader")
        self.assertEqual(request["input"][0]["content"][1]["detail"], "high")
        self.assertNotIn("temperature", request)
        schema = request["text"]["format"]["schema"]
        self.assertFalse(schema["additionalProperties"])
        self.assertEqual(set(schema["required"]), {"answer", "flag"})
        self.assertNotIn("default", schema["properties"]["flag"])
        self.assertEqual(response.parsed.answer, "example")
        self.assertEqual(response.usage_metadata.total_token_count, 15)

    def test_incomplete_and_refused_responses_are_never_accepted(self):
        for result in (
            SimpleNamespace(status="incomplete", output_text="partial"),
            SimpleNamespace(status="completed", output_text="",
                            output=[SimpleNamespace(content=[SimpleNamespace(type="refusal")])]),
        ):
            sdk = Mock()
            sdk.responses.create.return_value = result
            with self.subTest(result=result), self.assertRaises(ValueError):
                AzureClient(ENDPOINT, client=sdk).generate_content(model="school-grader", contents="test")

    def test_public_openai_and_embedded_credentials_are_rejected(self):
        for endpoint in ("https://api.openai.com", "http://school.openai.azure.com",
                         "https://school.openai.azure.com.evil.test",
                         "https://name:secret@school.openai.azure.com",
                         "https://school.openai.azure.com?key=secret"):
            with self.subTest(endpoint=endpoint), self.assertRaises(ValueError):
                AzureClient(endpoint, client=Mock())

    def test_oversized_image_group_is_rejected_before_sdk_call(self):
        sdk = Mock()
        with self.assertRaises(ValueError):
            AzureClient(ENDPOINT, client=sdk).generate_content(
                model="school-grader", contents=[ImagePart(b"x", "image/png")] * 11,
            )
        sdk.responses.create.assert_not_called()

    def test_usage_normalizes_cached_and_reasoning_tokens(self):
        usage = normalize_usage(SimpleNamespace(
            input_tokens=120, output_tokens=30, total_tokens=150,
            input_tokens_details=SimpleNamespace(cached_tokens=20),
            output_tokens_details=SimpleNamespace(reasoning_tokens=10),
        ))
        self.assertEqual((usage.prompt_token_count, usage.cached_content_token_count,
                          usage.thoughts_token_count), (120, 20, 10))


class TestAzureChunking(unittest.TestCase):
    def test_weighted_metadata_chunks_count_images_not_students(self):
        items = [{"script_index": i, "crops": {"ID": b"id", "CLASS": b"class", "NAME": b"name"}}
                 for i in range(35)]
        fake = Mock()

        def metadata(*, contents, **kwargs):
            indices = [int(value.split("#")[1].split("]")[0])
                       for value in contents if isinstance(value, str) and value.strip().startswith("--- [SCRIPT #")]
            parsed = MetadataBatchResponse(students=[
                StudentMetadataItem(script_index=i, id_ocr=str(i)) for i in indices
            ])
            return AIResponse(text=parsed.model_dump_json(), parsed=parsed)

        fake.generate_content.side_effect = metadata
        with patch("handwriting_grader.grading.AzureClient", return_value=fake):
            result = AzureGrader({"ocr": "gpt-5.4-mini"}, ENDPOINT, "v1").ocr_metadata_batch(items)
        self.assertEqual(len(result.students), 35)
        self.assertEqual(fake.generate_content.call_count, 12)
        for call in fake.generate_content.call_args_list:
            self.assertLessEqual(sum(isinstance(value, ImagePart) for value in call.kwargs["contents"]), 10)

    def test_question_chunks_validate_exact_script_identity(self):
        question = {"question_number": "Q1", "question_text": "Explain", "marking_scheme": "Example", "marks": 2}
        items = [{"script_index": i, "image": b"synthetic"} for i in range(25)]
        fake = Mock()

        def grades(*, contents, **kwargs):
            indices = [int(value.split("#")[1].split("]")[0])
                       for value in contents if isinstance(value, str) and value.strip().startswith("--- [SCRIPT #")]
            parsed = QuestionBatchGradeResponse(grades=[
                StudentBatchGradeItem(script_index=i, answer="example", mark=1,
                                      similarity_score=0.5, reasoning="matches") for i in indices
            ])
            return AIResponse(text=parsed.model_dump_json(), parsed=parsed)

        fake.generate_content.side_effect = grades
        with patch("handwriting_grader.grading.AzureClient", return_value=fake):
            grader = AzureGrader({"grading": "gpt-5.4"}, ENDPOINT, "v1")
            result = grader.grade_question_batch(question, items)
            self.assertEqual(len(result.grades), 25)
            self.assertEqual(fake.generate_content.call_count, 3)
            duplicate = grades(contents=["--- [SCRIPT #0] ---"])
            duplicate.parsed.grades.append(duplicate.parsed.grades[0])
            fake.generate_content.side_effect = None
            fake.generate_content.return_value = duplicate
            with self.assertRaises(ValueError):
                grader.grade_question_batch(question, items[:1])

    def test_payload_budget_can_split_below_image_limit(self):
        chunks = list(image_chunks([b"x" * 8_000_000] * 3, images=lambda item: [item]))
        self.assertEqual([len(chunk) for chunk in chunks], [1, 1, 1])
