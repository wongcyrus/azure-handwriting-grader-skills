import json
import os
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from pydantic import BaseModel

from handwriting_grader.azure_ai import (
    AIResponse, AzureClient, AzureIncompleteResponse, GenerationConfig, ImagePart, normalize_usage,
)
from handwriting_grader.grading import (
    AzureGrader, MetadataBatchResponse, QuestionBatchGradeResponse, StudentMetadataItem,
    StudentBatchGradeItem, batch_extract_metadata,
)


ENDPOINT = "https://school.openai.azure.com"


def sdk_client(sdk):
    return AzureClient(ENDPOINT, client=sdk, pricing_verifier=Mock(
        verify=Mock(return_value={"input": 2, "cached": 0.1, "output": 10}),
    ))


class Answer(BaseModel):
    answer: str
    flag: bool = False


class TestAzureTransport(unittest.TestCase):
    def test_identity_scope_matches_foundry_or_azure_openai_resource(self):
        for endpoint, scope in (
            ("https://images.services.ai.azure.com", "https://ai.azure.com/.default"),
            (ENDPOINT, "https://cognitiveservices.azure.com/.default"),
        ):
            credential = Mock()
            with self.subTest(endpoint=endpoint), \
                    patch.dict(os.environ, {"AZURE_OPENAI_API_KEY": "", "AZURE_OPENAI_AUTH": "default"}), \
                    patch("azure.identity.DefaultAzureCredential", return_value=credential), \
                    patch("azure.identity.get_bearer_token_provider", return_value=Mock()) as token_provider, \
                    patch("openai.OpenAI") as sdk:
                with AzureClient(endpoint, "v1"):
                    pass
                token_provider.assert_called_once_with(credential, scope)
                self.assertEqual(sdk.call_args.kwargs["base_url"], endpoint + "/openai/v1/")
                credential.close.assert_called_once()

    def test_structured_vision_uses_explicit_azure_route_and_no_storage(self):
        result = SimpleNamespace(status="completed", output_text='{"answer":"example","flag":false}',
                                 output=[], usage=SimpleNamespace(input_tokens=10, output_tokens=5, total_tokens=15))
        sdk = Mock()
        sdk.responses.create.return_value = result
        client = sdk_client(sdk)
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
                sdk_client(sdk).generate_content(model="school-grader", contents="test")

    def test_incomplete_response_preserves_filter_reason_and_request_id(self):
        sdk = Mock()
        sdk.responses.create.return_value = SimpleNamespace(
            status="incomplete", incomplete_details=SimpleNamespace(reason="content_filter"),
            _request_id="request-id",
        )
        with self.assertRaises(AzureIncompleteResponse) as caught:
            sdk_client(sdk).generate_content(model="school-grader", contents="test")
        self.assertEqual((caught.exception.status, caught.exception.reason, caught.exception.request_id),
                         ("incomplete", "content_filter", "request-id"))

    def test_public_openai_and_embedded_credentials_are_rejected(self):
        for endpoint in ("https://api.openai.com", "http://school.openai.azure.com",
                         "https://school.openai.azure.com.evil.test",
                         "https://name:secret@school.openai.azure.com",
                         "https://school.openai.azure.com?key=secret"):
            with self.subTest(endpoint=endpoint), self.assertRaises(ValueError):
                AzureClient(endpoint, client=Mock())

    def test_full_image_group_and_payload_reach_sdk_without_legacy_caps(self):
        sdk = Mock()
        sdk.responses.create.return_value = SimpleNamespace(
            status="completed", output_text="done", output=[], usage=None,
        )
        contents = [ImagePart(b"x" * (21 * 1024 * 1024), "image/png")]
        contents.extend([ImagePart(b"x", "image/png")] * 104)
        sdk_client(sdk).generate_content(
            model="gpt-6.1-sol", contents=contents,
        )
        sdk.responses.create.assert_called_once()
        parts = sdk.responses.create.call_args.kwargs["input"][0]["content"]
        self.assertEqual(len(parts), 105)
        self.assertTrue(all(part["type"] == "input_image" for part in parts))
        self.assertGreater(len(parts[0]["image_url"]), 20 * 1024 * 1024)

    def test_empty_and_unsupported_images_are_still_rejected(self):
        for data, mime_type in ((b"", "image/png"), (b"x", "text/plain")):
            with self.subTest(mime_type=mime_type), self.assertRaises(ValueError):
                ImagePart(data, mime_type)

    def test_usage_normalizes_cached_and_reasoning_tokens(self):
        usage = normalize_usage(SimpleNamespace(
            input_tokens=120, output_tokens=30, total_tokens=150,
            input_tokens_details=SimpleNamespace(cached_tokens=20),
            output_tokens_details=SimpleNamespace(reasoning_tokens=10),
        ))
        self.assertEqual((usage.prompt_token_count, usage.cached_content_token_count,
                          usage.thoughts_token_count), (120, 20, 10))

    def test_sdk_cache_write_metadata_reaches_telemetry_with_default_ttl(self):
        from openai.types.responses import ResponseUsage
        sdk = Mock()
        sdk.responses.create.return_value = SimpleNamespace(
            status="completed", output_text="done", output=[],
            usage=ResponseUsage.model_validate({
                "input_tokens": 100, "output_tokens": 10, "total_tokens": 110,
                "input_tokens_details": {"cached_tokens": 20, "cache_write_tokens": 50},
                "output_tokens_details": {"reasoning_tokens": 0},
            }),
        )
        response = sdk_client(sdk).generate_content(
            model="gpt-6.2-sol", contents="Grade",
        )
        self.assertEqual(response.usage_metadata.cache_write_token_count, 50)
        self.assertEqual(response.usage_metadata.cache_write_ttl, "30m")


class TestAzureChunking(unittest.TestCase):
    def test_metadata_batches_reach_transport_with_at_most_50_images(self):
        fake = Mock()

        def metadata(*, contents, **kwargs):
            indices = [int(value.split("#")[1].split("]")[0])
                       for value in contents if isinstance(value, str) and value.strip().startswith("--- [SCRIPT #")]
            parsed = MetadataBatchResponse(students=[
                StudentMetadataItem(script_index=i, id_ocr=str(i)) for i in indices
            ])
            return AIResponse(text=parsed.model_dump_json(), parsed=parsed)

        fake.generate_content.side_effect = metadata
        fields = ["ID", "CLASS", "NAME"]
        boxes = {field: (0, {}) for field in fields}
        with patch("handwriting_grader.grading.AzureClient", return_value=fake), \
                patch("handwriting_grader.grading.crop_image", return_value=b"image"):
            result = batch_extract_metadata(
                AzureGrader({"ocr": "gpt-5.4-mini"}, ENDPOINT, "v1"),
                list(range(58)), fields, boxes, 2, Path("."),
            )
        self.assertEqual(set(result), set(range(58)))
        self.assertEqual(
            [sum(isinstance(value, ImagePart) for value in call.kwargs["contents"])
             for call in fake.generate_content.call_args_list],
            [48, 48, 48, 30],
        )

    def test_metadata_rejects_more_than_50_images_before_calling_provider(self):
        items = [{"script_index": i, "crops": {"ID": b"id", "CLASS": b"class", "NAME": b"name"}}
                 for i in range(35)]
        fake = Mock()
        with patch("handwriting_grader.grading.AzureClient", return_value=fake):
            with self.assertRaisesRegex(ValueError, "exceeds 50 images"):
                AzureGrader({"ocr": "gpt-5.4-mini"}, ENDPOINT, "v1").ocr_metadata_batch(items)
        fake.generate_content.assert_not_called()

    def test_question_chunks_validate_exact_script_identity(self):
        question = {"question_number": "Q1", "question_text": "Explain", "marking_scheme": "Example", "marks": 2}
        items = [{"script_index": i, "image": b"synthetic"} for i in range(51)]
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
            for chunk_size, expected_sizes in ((50, [50, 1]), (100, [50, 1]), (20, [20, 20, 11])):
                with self.subTest(chunk_size=chunk_size):
                    fake.reset_mock()
                    result = grader.grade_question_batch(question, items, chunk_size=chunk_size)
                    self.assertEqual([grade.script_index for grade in result.grades], list(range(51)))
                    self.assertEqual(
                        [sum(isinstance(value, ImagePart) for value in call.kwargs["contents"])
                         for call in fake.generate_content.call_args_list],
                        expected_sizes,
                    )
            duplicate = grades(contents=["--- [SCRIPT #0] ---"])
            duplicate.parsed.grades.append(duplicate.parsed.grades[0])
            fake.generate_content.side_effect = None
            fake.generate_content.return_value = duplicate
            with self.assertRaises(ValueError):
                grader.grade_question_batch(question, items[:1])

    def test_question_batch_rejects_invalid_chunk_sizes(self):
        fake = Mock()
        with patch("handwriting_grader.grading.AzureClient", return_value=fake):
            grader = AzureGrader({"grading": "gpt-6.1-sol"}, ENDPOINT, "v1")
            for chunk_size in (0, -1, True, 1.5):
                with self.subTest(chunk_size=chunk_size), self.assertRaises(ValueError):
                    grader.grade_question_batch({}, [], chunk_size=chunk_size)
        fake.generate_content.assert_not_called()
