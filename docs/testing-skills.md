# Testing the Azure port safely

Test the CLI implementation and the human-reviewed skill separately. Use only
synthetic local fixtures: original student/example documents were intentionally
not copied into this port. There is no `examples/notebook-sample` dataset to use.

## Reproducible offline suite

From the Azure checkout, with Python 3.11+:

```sh
uv sync --frozen
uv run python -m unittest discover -s tests -v
```

Alternatively activate a Python environment, install with
`python -m pip install -e .`, and run `python -m unittest discover -s tests -v`.
Tests use synthetic data and fake Azure/SMTP services: they must not make paid
Azure calls or send real email. The current validation passed **160/160 tests**,
including the existing browser tests after restoring the optional `browser-test`
dependencies. The former sample-PDF test now uses a synthetically generated PDF;
no sample or student documents are required or copied. On other environments,
optional browser/LibreOffice dependencies may still be needed for those checks.
`pypdfium2` supplies local PDF rendering without a
required Poppler install; LibreOffice is required for actual answer-sheet DOCX
conversion. No live credential or deployment is necessary for offline tests.

## Skill behavior checks

Load `skills/handwriting-grading/` with its bundled references using your agent's
current documented registration mechanism. Check the exact loaded path rather
than assuming another checkout's copy is current. Ask:

> Use the handwriting-grading skill to explain a synthetic exam preflight and
> human approval gates. Do not make Azure calls, send email, write outputs or delete data.

The response should distinguish read-only preflight, cost consent, identity/score
review, hash-bound approval and separate dispatch consent. It should describe
`discover-models` as offline template generation, Azure deployment aliases, offline
review defaults and opt-in images. Merely loading a skill is not enforcement.

## Port acceptance checks

- Explicit HTTPS Azure endpoint and API version; no public OpenAI fallback.
- Responses calls use `store=False`; model names are deployment aliases.
- Offline template generation refuses overwrite and does not probe Azure.
- Default framework grading and direct Python fallback preserve artifact/gate schemas.
- Gemini-style groups send 50 question scripts or 35 metadata scripts together without
  image-count/payload micro-batching; batch means synchronous inference.
- Review/clustering start offline; paid embeddings require `--confirm-cost`.
- Reports are offline by default; image generation is explicitly opted in and never auto-retried.
- Pricing is per deployment, independently verified; unknown costs remain UNPRICED/null.
- Attendance, rubric, regions, scores, analysis and email approvals remain distinct.

Offline success establishes neither live availability, quota, grounding/image support,
OCR quality, large-cohort performance, grading accuracy nor real SMTP delivery.
Live validation would require separate data/cost authorization and is not part of
the offline test workflow. Never substitute a passing test for teacher approval.
