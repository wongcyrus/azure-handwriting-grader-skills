"""Synthetic Responses API payloads for localhost-only SDK tests."""

import json


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
