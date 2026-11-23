"""Synthetic Responses API payloads for localhost-only SDK tests."""

import copy
import json
from datetime import datetime, timezone

from handwriting_grader.pricing import configured_models


def manual_test_prices(config, endpoint="https://test.openai.azure.com", *, web_search=False):
    """Explicit synthetic approvals for the localhost GPT-5.4 SDK fixtures."""
    config = copy.deepcopy(config)
    config["azure_openai"]["endpoint"] = endpoint
    config["pricing_lookup"] = {"region": "eastus", "deployment_type": "global-standard"}
    source = {
        "verification": "manual", "verified_at": datetime.now(timezone.utc).isoformat(),
        "azure_endpoint": endpoint, "currency": "USD", "unit": "USD per million tokens",
        "source": "https://azure.microsoft.com/en-us/pricing/details/azure-openai/",
        **config["pricing_lookup"],
    }
    for deployment, family in configured_models(config).items():
        row = config.setdefault("pricing", {}).setdefault(deployment, {})
        for key, value in (("input", 2), ("cached", 0.1), ("output", 8)):
            row.setdefault(key, value)
        config.setdefault("pricing_sources", {})[deployment] = {**source, "model": family}
    if web_search:
        config["pricing_tools"] = {"web_search": {"per_1000_calls": 3}}
        config["pricing_tool_sources"] = {
            "web_search": {**source, "model": "web_search", "unit": "USD per 1000 calls"},
        }
    return config


def responses_body(text, sources=()):
    annotations = [
        {"type": "url_citation", "url": url, "title": title,
         "start_index": 0, "end_index": len(text)}
        for title, url in sources
    ]
    return json.dumps({
        "id": "resp_test", "object": "response", "created_at": 0,
        "status": "completed", "model": "test-deployment",
        "output": [{"id": "msg_test", "type": "message", "role": "assistant",
                    "status": "completed", "content": [
                        {"type": "output_text", "text": text, "annotations": annotations},
                    ]}],
        "usage": {"input_tokens": 12, "output_tokens": 4, "total_tokens": 16,
                  "input_tokens_details": {"cached_tokens": 0},
                  "output_tokens_details": {"reasoning_tokens": 0}},
    }).encode()
