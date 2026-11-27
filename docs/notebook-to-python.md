# Migrating an existing workflow to the Azure Python port

The Azure checkout is independent of the original provider repository. It does
not execute notebooks or automatically import notebook caches, scored files or
approvals. Original student and example documents were intentionally not copied.
Keep the original checkout and private source work intact; do not infer exact
scoring, formatting or notebook parity.

## Before creating approvals

Install Python 3.11+ with `uv sync --frozen`; see
[deployment configuration](model-configuration-and-caching.md) for pinned minimal
Microsoft Agent Framework dependencies and Azure authentication. Keep real YAML,
rosters, scans, credentials, output and caches outside Git.

Copy `exam.yaml.template` to a private location and explicitly set:

- Exam name, roster XLSX/sheet with ID, NAME, CLASS and stored leading zeroes.
- Scan PDF, pages per student and human-confirmed shared layout/order.
- Optional complete reviewed attendance; otherwise every roster entry is expected.
- Rubric XLSX/DOCX, private output directory and optional answer-sheet DOCX.
- Explicit pass threshold and equality policy if pass statistics/samples are desired.
- `exam.model_config` if using optional paid embeddings during review; otherwise
  those commands look for an adjacent `config.yaml`.

Relative input paths resolve from the exam YAML, not the checkout. Do not put
inputs inside the output directory. Changing settings invalidates approvals.
`reporting.advanced_analysis` and `email.enabled` are not automatic triggers.

Generate an offline Azure config with `discover-models --endpoint
https://RESOURCE.openai.azure.com --api-version v1 --write-config /private/config.yaml`.
It refuses overwrite and validates no live deployment or price. Replace illustrative
model names with actual Azure deployment aliases; independently verify image input,
structured outputs, embedding/image/search support and current regional rates.

## Equivalent stages, different provider

| Prior workflow task | Azure CLI task and decision |
|---|---|
| Printable personalized answer sheets | `answer-sheets`; local LibreOffice conversion, retained PDFs/mapping/combined PDF. Inspect pagination before printing. |
| Validate inputs | Offline `preflight`; basic input/page-count/dimension/approval checks remain. No heuristic orientation/order check or automatic alignment. Review scans manually; source corrections require fresh preparation, review and approvals. |
| Account for absences | `prepare-attendance`, review all statuses, `approve-attendance --confirm-reviewed`. Never infer absences. |
| Marking scheme | `import-rubric` for validated XLSX or paid `extract-rubric` for DOCX. Review every question and mark, then `approve-rubric`. |
| Optional fact check | Paid `verify-rubric` with Azure hosted `web_search` where supported. Check sources manually; does not approve the rubric. |
| Bounding boxes | `prepare-regions`, optional paid `suggest-regions`, `review-regions`, explicit approval. Local manual boxes remain possible. |
| OCR and grading | Preview and consent to `grade` (framework default) or `--orchestrator python`. Extract all students' metadata only, then automatically process answers only if IDs are nonempty, unique and cover the PRESENT roster exactly, preserving leading zeroes without requiring roster order. Otherwise stop with source PDF page/script diagnostics in private `grading/id-check.json`, an incomplete metadata checkpoint and no completed review workbook. Diagnostic is not approval. |
| Teacher score review | `review-grading` or XLSX; inspect identity and images, correct text/marks/reasoning, review every row, explicitly `approve-grading`. |
| Failure recovery | Preview `resume-grading` for supported interrupted runs, or `retry-grading` for completed failures; fresh cost consent. Preserve history. |
| One-question revision | Separate reviewed crop/rubric proposal and isolated child `regrade`; use `--run CHILD` for downstream stages. |
| Reports/statistics | Approved `report` and `analytics` are offline; inspect PDFs, scorebooks, samples and charts. |
| Feedback/Office reports | Paid `ai-analysis`, human review, `approve-analysis`, then offline `advanced-report`; images are opt-in, not default. |
| Distribution | `preview-email`, inspect recipients/body/attachments, `approve-email`, then separate `send-email --confirm-send`. No automatic dispatch. |
| Retention | Preview `clean`; explicit `--confirm-delete`, slim ZIP backup by default, review/final artifacts preserved. Shared cache retention is separate. |

Paid stages requiring targets use `--model-config /private/config.yaml --endpoint
https://RESOURCE.openai.azure.com --api-version v1`; add `--confirm-cost` only after
approval. Retry/resume use their recorded run target. Review/clustering remain
local unless `--confirm-cost` explicitly permits embeddings. Optional images use
`advanced-report --infographics --confirm-cost [--image-model DEPLOYMENT]` and need
an Azure image deployment (`models.analytics_image` or override). No image retries.

## Preserved human controls and remaining limits

Approval hashes bind current artifacts and inputs, not just timestamps. Edited
workbooks/crops invalidate downstream approval; old reports do not automatically
disappear. Failed or flagged grades and corrected answers need manual marks.
Similarity suggestions save unreviewed drafts, not approvals. Local editors are
single-user tools; keep bearer-token URLs private and stop them after review.

There is no global cohort consistency, exact OCR match, fixed cost saving or
latency guarantee. Requests contain at most 50 images, including up to 16 metadata
scripts with three fields. Payload and deployment limits can reject requests. Text moderation
cannot re-inspect diagrams.
`store=False` is not a guarantee about every Azure retention policy. Verify resource
policy and deployment behavior before separately authorized live use.

Read the [detailed workflow](../.github/skills/handwriting-grading/references/flow-and-parity.md),
[score review](score-review-and-approval.md), [email](email-distribution-architecture.md),
[retention](cleanup-and-retention-design.md) and [offline tests](testing-skills.md).
