"""Azure-only multimodal transport shared by the reviewed grading stages."""

import base64
import copy
import json
import math
import os
from dataclasses import dataclass, field
from types import SimpleNamespace
from urllib.parse import urlsplit

from pydantic import BaseModel


MAX_IMAGES = 10
MAX_IMAGE_BYTES = 20 * 1024 * 1024
MAX_INLINE_BYTES = 18 * 1024 * 1024


def validate_endpoint(endpoint):
    if not isinstance(endpoint, str):
        raise ValueError("An explicit Azure OpenAI HTTPS endpoint is required")
    parsed = urlsplit(endpoint)
    hostname = (parsed.hostname or "").lower()
    suffixes = (".openai.azure.com", ".openai.azure.us", ".openai.azure.cn",
                ".services.ai.azure.com")
    if (parsed.scheme != "https" or not hostname.endswith(suffixes)
            or parsed.username or parsed.password or parsed.query or parsed.fragment
            or parsed.port not in (None, 443) or parsed.path not in ("", "/")):
        raise ValueError("Use an Azure resource HTTPS endpoint without paths, credentials or query parameters")
    return endpoint.rstrip("/")


@dataclass(frozen=True)
class ImagePart:
    data: bytes
    mime_type: str

    def __post_init__(self):
        if self.mime_type not in ("image/png", "image/jpeg", "image/webp"):
            raise ValueError("Unsupported image MIME type")
        if not self.data or len(self.data) > MAX_IMAGE_BYTES:
            raise ValueError("Image must be nonempty and at most 20 MiB")


@dataclass(frozen=True)
class ReasoningConfig:
    effort: str = "medium"


@dataclass
class GenerationConfig:
    temperature: float | None = None
    max_output_tokens: int = 8192
    response_mime_type: str | None = None
    response_schema: type[BaseModel] | None = None
    thinking_config: ReasoningConfig | None = None
    tools: list[str] = field(default_factory=list)


@dataclass
class Usage:
    prompt_token_count: int = 0
    candidates_token_count: int = 0
    total_token_count: int = 0
    cached_content_token_count: int = 0
    thoughts_token_count: int = 0


@dataclass
class AIResponse:
    text: str | None = None
    parsed: BaseModel | None = None
    usage_metadata: Usage | None = None
    sources: list[dict] = field(default_factory=list)
    image_bytes: bytes | None = None
    embeddings: list = field(default_factory=list)


def normalize_usage(usage):
    if usage is None:
        return None
    inp = getattr(usage, "input_tokens", getattr(usage, "prompt_tokens", 0)) or 0
    out = getattr(usage, "output_tokens", getattr(usage, "completion_tokens", 0)) or 0
    input_details = getattr(usage, "input_tokens_details", None)
    if input_details is None:
        input_details = getattr(usage, "prompt_tokens_details", None)
    output_details = getattr(usage, "output_tokens_details", None)
    if output_details is None:
        output_details = getattr(usage, "completion_tokens_details", None)
    return Usage(inp, out, getattr(usage, "total_tokens", 0) or inp + out,
                 getattr(input_details, "cached_tokens", 0) or 0,
                 getattr(output_details, "reasoning_tokens", 0) or 0)


def strict_schema(model):
    schema = copy.deepcopy(model.model_json_schema())

    def visit(node):
        if isinstance(node, dict):
            node.pop("default", None)
            if node.get("type") == "object" or "properties" in node:
                node["additionalProperties"] = False
                node["required"] = list(node.get("properties", {}))
            for value in node.values():
                visit(value)
        elif isinstance(node, list):
            for value in node:
                visit(value)

    visit(schema)
    return schema


def image_chunks(items, *, images, chunk_size=MAX_IMAGES):
    """Bound both image count and encoded payload without splitting one script."""
    if type(chunk_size) is not int or chunk_size <= 0:
        raise ValueError("Chunk size must be a positive integer")
    chunk, count, size = [], 0, 0
    for item in items:
        parts = list(images(item))
        item_count = len(parts)
        item_size = sum(4 * math.ceil(len(data) / 3) for data in parts)
        if item_count > MAX_IMAGES or item_size > MAX_INLINE_BYTES:
            raise ValueError("One script exceeds the Azure image request budget")
        if chunk and (len(chunk) >= chunk_size or count + item_count > MAX_IMAGES
                      or size + item_size > MAX_INLINE_BYTES):
            yield chunk
            chunk, count, size = [], 0, 0
        chunk.append(item)
        count += item_count
        size += item_size
    if chunk:
        yield chunk


class AzureClient:
    def __init__(self, endpoint, api_version="v1", *, max_retries=2, timeout=180, client=None):
        self.endpoint = validate_endpoint(endpoint)
        if not isinstance(api_version, str) or not api_version.strip():
            raise ValueError("Azure OpenAI API version is required")
        self.api_version = api_version
        self._credential = None
        self._owned = client is None
        if client is not None:
            self.client = client
            return
        from openai import AzureOpenAI, OpenAI

        key = os.environ.get("AZURE_OPENAI_API_KEY")
        if not key:
            from azure.identity import (
                DefaultAzureCredential, ManagedIdentityCredential, get_bearer_token_provider,
            )
            auth = os.environ.get("AZURE_OPENAI_AUTH", "default")
            if auth not in ("default", "managed_identity"):
                raise ValueError("AZURE_OPENAI_AUTH must be default or managed_identity")
            self._credential = (ManagedIdentityCredential() if auth == "managed_identity"
                                else DefaultAzureCredential())
            key = get_bearer_token_provider(self._credential, "https://cognitiveservices.azure.com/.default")
        options = {"max_retries": max_retries, "timeout": timeout}
        if api_version == "v1":
            self.client = OpenAI(base_url=f"{self.endpoint}/openai/v1/", api_key=key, **options)
        else:
            auth_options = {"azure_ad_token_provider": key} if callable(key) else {"api_key": key}
            self.client = AzureOpenAI(azure_endpoint=self.endpoint, api_version=api_version,
                                     **auth_options, **options)

    def __enter__(self):
        return self

    def close(self):
        if self._owned:
            self.client.close()
        if self._credential is not None:
            self._credential.close()

    def __exit__(self, *exc):
        self.close()

    def generate_content(self, *, model, contents, config=None):
        config = config or GenerationConfig()
        values = [contents] if isinstance(contents, str) else list(contents)
        parts = []
        for value in values:
            if isinstance(value, str):
                parts.append({"type": "input_text", "text": value})
            elif isinstance(value, ImagePart):
                encoded = base64.b64encode(value.data).decode("ascii")
                parts.append({"type": "input_image", "image_url":
                              f"data:{value.mime_type};base64,{encoded}", "detail": "high"})
            else:
                raise ValueError("Model contents must be text or image parts")
        if sum(p["type"] == "input_image" for p in parts) > MAX_IMAGES:
            raise ValueError("Azure request exceeds the conservative ten-image limit")
        if len(json.dumps(parts).encode()) > 20 * 1024 * 1024:
            raise ValueError("Azure request exceeds the inline payload budget")
        request = {
            "model": model, "input": [{"role": "user", "content": parts}],
            "max_output_tokens": config.max_output_tokens,
            "store": False,
        }
        # Deployment aliases need not disclose the underlying model family.
        if config.temperature is not None and model.lower().startswith("gpt-4"):
            request["temperature"] = config.temperature
        if config.thinking_config is not None:
            request["reasoning"] = {"effort": config.thinking_config.effort}
        if config.response_schema is not None:
            request["text"] = {"format": {
                "type": "json_schema", "name": config.response_schema.__name__,
                "schema": strict_schema(config.response_schema), "strict": True,
            }}
        elif config.response_mime_type == "application/json":
            request["text"] = {"format": {"type": "json_object"}}
        if config.tools:
            if config.tools != ["web_search"]:
                raise ValueError("Unsupported hosted tools")
            request["tools"] = [{"type": "web_search"}]
        result = self.client.responses.create(**request)
        if getattr(result, "status", "completed") != "completed":
            raise ValueError("Azure response is incomplete or failed; no result accepted")
        text = getattr(result, "output_text", None)
        sources = []
        for item in getattr(result, "output", []) or []:
            for content in getattr(item, "content", []) or []:
                if getattr(content, "type", None) == "refusal":
                    raise ValueError("Azure model refused the request")
                for annotation in getattr(content, "annotations", []) or []:
                    if getattr(annotation, "type", None) == "url_citation":
                        sources.append({"title": annotation.title, "url": annotation.url})
        parsed = None
        if config.response_schema is not None:
            if not text:
                raise ValueError("Azure structured response did not return text")
            parsed = config.response_schema.model_validate_json(text)
        return AIResponse(text, parsed, normalize_usage(getattr(result, "usage", None)), sources)

    def embed_content(self, *, model, contents):
        result = self.client.embeddings.create(model=model, input=contents)
        embeddings = [SimpleNamespace(values=item.embedding)
                      for item in sorted(result.data, key=lambda item: item.index)]
        return AIResponse(usage_metadata=normalize_usage(getattr(result, "usage", None)),
                          embeddings=embeddings)

    def generate_image(self, *, model, prompt, size="1536x1024"):
        # Image requests deliberately do not automatically retry paid generation.
        result = self.client.with_options(max_retries=0).images.generate(
            model=model, prompt=prompt, size=size, n=1,
        )
        if not result.data or not result.data[0].b64_json:
            raise ValueError("Azure image generation returned no inline image")
        return AIResponse(image_bytes=base64.b64decode(result.data[0].b64_json, validate=True),
                          usage_metadata=normalize_usage(getattr(result, "usage", None)))
