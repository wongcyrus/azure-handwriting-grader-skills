"""Offline Azure deployment configuration; model IDs are not deployment names."""

import re
from pathlib import Path

import yaml

from .azure_ai import validate_endpoint


def validate_model_eligibility(model, agent=None):
    if not isinstance(model, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", model):
        raise ValueError(f"Invalid Azure deployment name for {agent}")
    if model.lower().startswith(("gemini", "imagen", "veo", "claude", "publishers")):
        raise ValueError("This port supports Azure OpenAI deployments only")
    if agent not in ("embedding", "analytics_image") and model.startswith(("text-embedding-", "gpt-image-", "dall-e")):
        raise ValueError("Grading requires an image-input, structured-output chat deployment")
    if agent == "embedding" and model.startswith(("gpt-", "o1", "o3", "o4")):
        raise ValueError("The embedding stage requires an embedding deployment")
    if agent == "analytics_image" and model.startswith(("text-embedding-", "gpt-4.", "gpt-5")):
        raise ValueError("Infographics require an image-generation deployment")


def write_model_config(target, endpoint, api_version="v1"):
    endpoint = validate_endpoint(endpoint)
    config = {
        "azure_openai": {"endpoint": endpoint, "api_version": api_version},
        "models": {
            "annotation": "gpt-4.1",
            "marking_scheme": "gpt-4.1-mini",
            "ocr": "gpt-4.1-mini",
            "batch_metadata_ocr": "gpt-4.1-mini",
            "grading": "gpt-4.1",
            "batch_grading": "gpt-4.1",
            "moderation": "gpt-4.1",
            "analytics": "gpt-4.1",
            "student_feedback": "gpt-4.1-mini",
            "embedding": "text-embedding-3-small",
        },
        "caching": {"enabled": False, "scope": "run", "agents": {}},
        "pricing": {},
    }
    target = Path(target)
    with target.open("x", encoding="utf-8") as file:
        yaml.safe_dump(config, file, sort_keys=False)
    return config


def discover_and_report(endpoint, api_version="v1", write_config=None):
    validate_endpoint(endpoint)
    print("Azure deployment names must be configured in your resource; no inference probes or pricing discovery are performed.")
    print("Use image-input and structured-output deployments. Names below are examples, not verified deployments.")
    if write_config is not None:
        config = write_model_config(write_config, endpoint, api_version)
        print(f"Template written to {write_config}; edit deployment names and verified pricing before use.")
        return config
    return {"azure_openai": {"endpoint": endpoint, "api_version": api_version}}
