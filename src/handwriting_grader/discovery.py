"""Offline Azure deployment configuration; model IDs are not deployment names."""

import re
from pathlib import Path

import yaml

from .azure_ai import validate_endpoint


MODEL_RECOMMENDATIONS_CHECKED = "2026-11-23"
MODEL_CATALOG_URL = (
    "https://learn.microsoft.com/en-us/azure/foundry/foundry-models/"
    "concepts/models-sold-directly-by-azure"
)
RECOMMENDED_MODELS = (
    ("gpt-6.1-terra", "2026-10-26", "Visual crops, bounding boxes and diagram grading"),
    ("gpt-6-luna", "2026-09-22", "Efficient OCR, rubric extraction and student feedback"),
    ("gpt-6.2-sol", "2026-11-17", "General reasoning, moderation and analytics"),
    ("gpt-6.2-astra", "2026-11-17", "Evaluate for difficult rubric and moderation tasks"),
    ("gpt-6.1-sol", "2026-09-29", "GPT-6.1 alternative for reasoning and grading"),
)


def validate_model_eligibility(model, agent=None, *, base_model=None):
    if not isinstance(model, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", model):
        raise ValueError(f"Invalid Azure deployment name for {agent}")
    name = model.lower()
    if name.startswith(("gemini", "imagen", "veo", "claude", "publishers")):
        raise ValueError("This port supports Azure OpenAI deployments only")
    if agent not in ("embedding", "analytics_image"):
        family = base_model if base_model is not None else model
        version = re.fullmatch(r"gpt-(\d+)(?:[.-][a-z0-9_.-]+)?", family.lower()) if isinstance(family, str) else None
        if not version or int(version.group(1)) < 5:
            raise ValueError(
                "Text/vision stages require GPT-5 or newer; "
                "declare deployment_models.<deployment> for custom aliases"
            )
    if agent == "embedding" and name.startswith(("gpt-", "o1", "o3", "o4")):
        raise ValueError("The embedding stage requires an embedding deployment")
    if agent == "analytics_image" and (
            name.startswith(("text-embedding-", "dall-e"))
            or re.match(r"gpt-\d", name)):
        raise ValueError("Infographics require an image-generation deployment")


def write_model_config(target, endpoint, api_version="v1"):
    endpoint = validate_endpoint(endpoint)
    config = {
        "azure_openai": {"endpoint": endpoint, "api_version": api_version},
        "models": {
            "annotation": "gpt-6.1-terra",
            "marking_scheme": "gpt-6-luna",
            "ocr": "gpt-6-luna",
            "batch_metadata_ocr": "gpt-6-luna",
            "grading": "gpt-6.1-terra",
            "batch_grading": "gpt-6.1-terra",
            "moderation": "gpt-6.2-sol",
            "analytics": "gpt-6.2-sol",
            "student_feedback": "gpt-6-luna",
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
    print(f"Curated GA text/vision recommendations (documentation snapshot: {MODEL_RECOMMENDATIONS_CHECKED}):")
    print("| Model family | Azure model version | Suggested evaluation |")
    print("|---|---|---|")
    for model, version, purpose in RECOMMENDED_MODELS:
        print(f"| {model} | {version} | {purpose} |")
    print(f"Source: {MODEL_CATALOG_URL}")
    print("This snapshot excludes preview, legacy, deprecated, retired and older-generation recommendations; it is not an exhaustive support list.")
    print("Recheck lifecycle, regional availability, capabilities, quota and pricing in Azure before deployment; no live verification is performed.")
    print("These are evaluation candidates, not verified handwriting benchmarks or deployed aliases. Existing explicit GPT-5+ configurations remain supported.")
    if write_config is not None:
        config = write_model_config(write_config, endpoint, api_version)
        print(f"Template written to {write_config}; edit deployment names and verified pricing before use.")
        return config
    return {"azure_openai": {"endpoint": endpoint, "api_version": api_version}}
