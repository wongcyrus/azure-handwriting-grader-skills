---
name: handwriting-grading
description: >-
  Guides preparation and human review of scanned handwriting grading with
  Azure OpenAI Handwriting Grader. Use for exam configuration, input validation,
  rubric and bounding-box review, grading review, reports, or safe planning
  of student-score distribution. Does not provide a general OCR service or
  authorize automated grading or email.
version: 1
---

# Human-reviewed handwriting grading

## Prerequisites

Use Python 3.11+ and the Azure checkout. Prefer `uv sync --frozen`, then
`uv run handwriting-grader`; alternatively install with `python -m pip install -e .`
in an activated environment. The package pins minimal Microsoft Agent Framework
core/OpenAI packages, not the umbrella `agent-framework` package. See
[dependency and Azure configuration details](../../../docs/model-configuration-and-caching.md).
Do not install Google ADK or provider SDKs for this port.

### Cross-platform support
PDF page rendering is powered by pure-Python `pypdfium2` and works out of the box across Windows, macOS, and Linux without external Poppler or `pdftoppm` installs.

### Installation & Execution
Install the tool into your Python environment:
```bash
pip install -e /path/to/azure-handwriting-grader-skills
```
Once installed, `handwriting-grader` is available globally on your `PATH` (or via `.venv/bin/handwriting-grader` on Unix / `.venv\Scripts\handwriting-grader` on Windows).

All `--exam "/path/to/exam.yaml"` and `--model-config "/path/to/config.yaml"` paths can be located anywhere on the filesystem (always quote paths in shell commands in case directories contain spaces); all relative paths declared inside `exam.yaml` resolve relative to `exam.yaml`'s parent folder, not the current working directory.

## Scope and availability

Use the Python tools in this repository, not notebooks. Answer sheets, preflight, rubric
import/extraction, explicit reviewed attendance, region review, Azure grading, human score review and
basic reports, offline statistics, optional search-grounded verification,
reviewed AI analysis, resumable checkpoints, opt-in
model caches, targeted question regrading and gated email are implemented. Report formatting and cache
coverage differ from the notebooks.
Stop and tell the user when a requested stage is unavailable; never simulate success,
execute a notebook as a workaround, or claim a human approval occurred.

## Safety

- Treat scans, rosters, feedback, output, cache and notebook output as student
  data. Never commit or share them without authorization.
- Do not overwrite inputs or outputs, delete history, restart a user's session,
  call a paid model or send email without the relevant explicit approval.
- Never infer approval from a saved file, a passing test or a model response.
- Local skill instructions alone are not an enforcement mechanism.
- **Azure-only model boundary**: Use explicit HTTPS Azure endpoint/API version and
  configured Azure deployment aliases. Image stages need image input and structured
  outputs; embeddings/images need distinct compatible deployment types. Offline name
  checks do not verify actual capabilities or quality. No public OpenAI fallback.
- `discover-models --endpoint https://RESOURCE.openai.azure.com --api-version v1
  --write-config /private/config.yaml` is offline template generation, not discovery,
  pricing or quota probing, and refuses overwrite. Inspect actual deployments separately.
- Calls use Azure SDK Responses with `store=False`; verify Azure retention and region
  policies independently. Credentials stay in environment/identity, never files:
  optional `AZURE_OPENAI_API_KEY`, otherwise `DefaultAzureCredential`; production
  `AZURE_OPENAI_AUTH=managed_identity`.
- **Cost governance**: Before every paid stage, preview target, transferred data and
  estimated requests; independently verify rates for the selected deployment's
  retail meter profile and
  obtain `--confirm-cost`. The first actual AI request of each run refreshes/checks
  pricing; missing, ambiguous, stale manual or changed rates block requests.
  Follow `references/pricing.md`; price verification never grants inference consent.
  No default rates are guessed; missing usage in historical reports is UNPRICED/null.
  Afterward run `cost-report --exam /private/exam.yaml` and report recorded
  successful-call usage, priced estimates, missing pricing and failures from
  `azure_usage.jsonl`. SDK retry attempts and failed responses are not individually
  logged with token usage; never claim authoritative billed counts or actual total
  spend including every retry. Azure billing is authoritative.
  Opening review/clustering is offline unless embeddings are explicitly consented.

## Prepare an exam

1. Establish whether the user is starting or resuming, what stage they need,
   and which local paths they intend to use. Do not copy or overwrite data.
   Before preflight, `suggest-scan-markers`, `check-scans`, or any other stage,
   collect the complete Azure profile in one explicit setup step:
   - **Text/vision resource:** HTTPS resource root, API version, deployment
     aliases and underlying models for annotation, OCR, rubric extraction,
     grading, moderation, analytics and student feedback.
   - **Embedding resource:** endpoint, API version and deployment, or an
     explicit decision to keep semantic clustering disabled.
   - **Image-generation resource:** endpoint, API version and
     `models.analytics_image` deployment, or an explicit decision to keep
     infographic generation disabled. Ask about this even if the current stage
     only needs text/vision.
   - **Commercial/access details:** resource ARM region, deployment/billing type,
     retail meter region/profile, independently reviewed rates, authentication
     method, intended caching, and any separate/private configuration file paths.
     A resource location is not necessarily the Azure retail meter `armRegionName`.
     For Global Standard GPT-6 deployments, first query the supplied profile. If it
     is entirely `UNPRICED`, inspect existing priced configurations and offer the
     current verified meter-profile region (commonly `eastus`) as an explicit
     user-reviewed alternative. Refresh it rather than trusting historical rates;
     never silently substitute a region, rewrite approved configuration, or treat
     a successful lookup as inference/data-transfer consent.
   Present the detected values and ask for every missing or ambiguous value.
   Do not infer shared endpoints, deployment names, regions or billing types.
   Generate and verify the private text/vision and image configurations before
   continuing; later stage-specific `--confirm-cost` consent is still required.
   When resuming an existing workspace or `output_dir`, inspect existing files
   and artifacts to orient immediately (do not rely on prior conversation history):

   | Latest Artifact Present | Completed Stage | Next Command / Action |
   |---|---|---|
   | No `exam.yaml` / `config.yaml` | Not configured | `discover-models` (for `config.yaml`) -> configure `exam.yaml` -> `preflight` -> `check-scans` |
   | `exam.yaml` exists (no `rubric/` or `attendance/`) | Configured | `preflight` -> `check-scans` -> `prepare-attendance` (if configured) or `extract-rubric`/`import-rubric` |
   | No `scan-markers/approval.json` | Printed scan markers not approved | Preview `suggest-scan-markers` with explicit cost/data consent before paid calls -> teacher reviews markers and first-script order -> `approve-scan-markers` -> paid Azure `check-scans` before region setup or grading |
   | `attendance/review.xlsx` (no `attendance/approval.json`) | Attendance extracted | Teacher reviews `attendance/review.xlsx` -> `approve-attendance` |
   | `rubric/rubric.xlsx` (no `rubric/approval.json`) | Rubric extracted/imported | Teacher reviews `rubric/rubric.xlsx` -> `approve-rubric` |
   | `rubric/approval.json` (no `regions/images/`) | Rubric approved | `prepare-regions` -> optional paid `suggest-regions` -> `review-regions` |
   | `regions/images/` (no `regions/ai_suggestions.json`, no `regions/approval.json`) | Region pages rendered | Optional `suggest-regions` (preview and consent first), or local manual `review-regions` |
   | `regions/ai_suggestions.json` or `regions/draft.json` (no `regions/approval.json`) | Regions suggested/drafted | `review-regions` (adjust boxes & approve) or `approve-regions` |
   | `regions/approval.json` (no `grading/`) | Regions approved | `grade` (preview first, then `--confirm-cost`) |
   | `grading/checkpoint.json` (no `grading/manifest.json`) | Grading interrupted | `resume-grading` (preview first, then `--confirm-cost`) |
   | `grading/manifest.json`, `results.json` with `completed: false` | Grading interrupted | `resume-grading` (preview first, then `--confirm-cost`) |
   | `grading/manifest.json`, `results.json` with `completed: true` (no `grading/approval.json`) | Grading done (or failed items) | `cluster-answers` (optional) -> `review-grading` (or `retry-grading` if failures) -> approve |
   | `grading/approval.json` | Scores approved | Present Post-Approval Menu: `report`, `analytics`, `ai-analysis` (optional) |
   | `reports/manifest.json` or `analytics/manifest.json` | Reports / offline stats generated | Offer remaining options: `analytics`/`report` (if missing), `ai-analysis` -> `advanced-report`, `moodle-export` (LMS PDFs/ZIP/CSV), `preview-email` -> `send-email`, or `clean` |
   | `ai-analysis/review.xlsx` (no `ai-analysis/approval.json`) | AI analysis generated | Teacher reviews `ai-analysis/review.xlsx` -> `approve-analysis` |
   | `ai-analysis/approval.json` | AI analysis approved | `advanced-report` (Teacher DOCX & Class PPTX), `preview-email` -> `send-email`, or `clean` |
   | `email/` preview artifact (no `email/approval.json`) | Email preview generated | Teacher inspects preview -> `approve-email` -> `send-email` |
   | `runs/<child>/` directory | Targeted single-question regrade | Inspect artifacts inside `runs/<child>/` and pass `--run <child>` to commands |

2. Read `references/configuration.md` and examine existing settings. Present
   detected values and ask for missing or ambiguous decisions. Keep actual
   configuration outside version control:
   a. Exam settings (`exam.yaml`): define roster, scans, layout, attendance, and reporting.
   b. AI model configuration (`config.yaml`): inspect all existing Azure
      configurations rather than overwriting them. Otherwise, only after the
      up-front profile is complete, generate separate text/vision/embedding and
      optional image-generation templates with
      `discover-models --endpoint https://RESOURCE.openai.azure.com --api-version v1
      --write-config /private/config.yaml`, then set actual deployment aliases and
      verified rates. This does not confirm availability, quota or capabilities.
      The canonical checked-in alternative is the root
      [model template](../../../model-config.yaml.template), not an `example/` copy.
3. If the user needs printable answer sheets before scans exist, read
   `references/answer-sheets.md` and run that independent stage first.
4. Run preflight checks:
   `handwriting-grader preflight --exam /path/to/exam.yaml`.
   It makes no Azure calls and does not create outputs.
5. Fix reported errors with the user's input and rerun. A successful preflight
   does not verify scan order, leading zeroes, rubric contents, credentials,
   model access or approval.
   **Prepare reviewed printed markers, then run `check-scans` BEFORE region setup**:
   Preview `suggest-scan-markers --exam /path/to/exam.yaml --model-config /private/config.yaml
   --endpoint https://RESOURCE.openai.azure.com --api-version v1`.
   It proposes page-unique printed phrases from the first student's script through
   a Microsoft Agent Framework workflow using `models.annotation`. Obtain separate
   cost/data consent before `--confirm-cost`. The teacher must review the first
   script's order and `output_dir/scan-markers/markers.json` against the saved images,
   then explicitly run `approve-scan-markers --exam /path/to/exam.yaml --confirm-reviewed`.
   Tesseract and the selected language pack must be installed locally.
   `handwriting-grader check-scans --exam /path/to/exam.yaml
   --model-config /private/config.yaml --endpoint https://RESOURCE.openai.azure.com
   --api-version v1`.
   Preview the crop count and obtain explicit data/cost consent, then add
   `--confirm-cost`. Locally combine all reviewed markers for each student's script
   into one composite image. Azure requests send at most 50 script images each, so
   a 58-student, two-page exam uses 58 script images—not 116 individual marker
   images—and covers the complete PDF across the previewed request count. No
   confirmation is committed until every batch succeeds. A clearly printed
   standalone question label is valid when it uniquely identifies the page and the
   teacher verifies its exact box. Do not send whole answer pages or use
   handwritten OCR substitutions.
   The hash-bound `azure_confirmation-v2.json` is required by grading. Missing,
   unreadable or ambiguous markers block grading, as do wrong-page matches. The first
   script is a human-confirmed reference, not independent proof of correct order.
   If any page is flagged, **do not
   silently flip or reorder pages in code** — report the exact PDF page numbers and
   script numbers to the user so they fix the physical scan or source PDF manually
   and re-run `check-scans`.
   If attendance is configured, read `references/attendance.md` and obtain
   explicit review and approval before grading.
6. For rubric setup (MUST run BEFORE region suggestion so exact question IDs are known), read `references/grading.md`:
   a. If the marking scheme is a DOCX, run `extract-rubric` (preview first,
      obtain cost consent, then `--confirm-cost`) to extract questions and
      marks into `output_dir/rubric/rubric.xlsx` using Azure OpenAI.
   b. If the marking scheme is an existing XLSX, run `import-rubric`.
   c. Have the teacher inspect `rubric.xlsx` and explicitly approve with
      `approve-rubric --exam /path/to/exam.yaml --confirm-reviewed`.
7. For region setup and review, read `references/regions.md`:
   a. Run `handwriting-grader prepare-regions --exam /path/to/exam.yaml`
      to render the first script's page images into `output_dir/regions/images/`.
   b. Optionally preview Azure `suggest-regions` (`models.annotation`) with
      `--model-config /private/config.yaml --endpoint https://RESOURCE.openai.azure.com
      --api-version v1`; obtain separate cost/data consent before `--confirm-cost`.
      Proposals use rubric question IDs. Local manual region drawing remains available
      without any paid suggestion. Every page still needs human review and approval.
   c. Start the local server with `review-regions --exam /path/to/exam.yaml`.
      Provide the URL so the user can inspect the automatically loaded AI proposals
      across all pages, adjust boxes (`ID`, `NAME`, `CLASS`, questions), save each
      page, and approve. Alternatively, after manual or programmatic edits to
      `annotations.json`, approve with:
      `handwriting-grader approve-regions --exam /path/to/exam.yaml --confirm-reviewed`.
   d. **Automatic Page Alignment & Scanner Shift Recovery**:
      During `grade`, every scanned page is automatically aligned against `regions/images/`
      before cropping. For an existing unaligned run or tight boxes, follow the recovery
      commands (`retry-grading --align-images ...`) in `references/regions.md`.
8. For grading, reporting and AI analysis read `references/grading.md`.
   Obtain the specified human confirmations; never infer approval.
   - For current Azure prices, read `references/pricing.md`. Obtain the resource
     location, retail meter region/profile and Standard deployment type before
     `fetch-pricing`; never infer them from an endpoint. Preview public retail rates
     without inference or credentials. If the first Global Standard query has no
     effective meters, present a refreshed alternative meter profile for user
     confirmation instead of stopping without checking known priced configurations.
     Save only when requested, using `--write-config` to a new private file; review
     meter provenance and keep missing/ambiguous prices UNPRICED. Discovery and
     preflight stay offline. A pricing lookup is not approval for paid grading.
   - `grade` defaults to `--orchestrator agent-framework`: real Executor/WorkflowBuilder
     validation → existing grading → human-review boundary. `workflow-grade` forces it;
     `--orchestrator python` is the direct fallback. No autonomous approval or email.
     Core transport remains synchronous with question threads; framework clients are
     not shared across OS threads.
   - `--mode batch` is synchronous multi-image inference, **not Azure asynchronous Batch**.
     Requests contain at most 50 images: up to 50 question scripts or 16 metadata
     scripts with three fields. Metadata batch failures stop the run; do not
     automatically fall back to paid single-field requests. Payload, deployment,
     context, output and quota limits can still reject requests. Comparisons occur within
     groups, not guaranteed across the whole cohort.
   - By default a question batch error stops grading. For original batch runs only,
     `grade` or `resume-grading --continue-on-image-policy-block` opts in to continue
     after the specific Azure image-policy block. Preview and obtain explicit data and
     cost consent first: later questions still send images and incur charges. This does
     not bypass Azure filtering or retry blocked images. Affected nonblank answers are
     unscored and flagged for mandatory human review; other errors still stop the run.
     With concurrent questions, already submitted requests can finish after an error.
   - `--mode item` grades individual crops, then moderates text. Image/payload limits
     still apply, and diagrams need image review. Both modes preserve artifact schemas.
     Choose by actual deployment behavior and preview; promise no fixed savings/runtime.
   - Pillow filters clearly blank answers locally. Roster candidates assist metadata
     OCR but do not guarantee exact matches: verify every identity and answer.

   **Failure Diagnostics, Quota Protection, and User-Decision Gating**:
   - The engine uses bounded Azure SDK retries. **Never write ad-hoc Python retry loops.**
   - If grading finishes with failed marks (`grading_failed=True`) or moderation errors, **notify the user immediately** with the failed count, affected question numbers, and error types (`429`, `504`, `5xx`), and ask them to choose:
     - **Option A (Targeted Retry)**: For incomplete batch runs without review workbooks, preview `handwriting-grader retry-failed-batches --exam /path/to/exam.yaml`; for other runs preview `retry-grading`. Obtain cost consent before `--confirm-cost`. The batch retry stops on the first failure and does not resume unprocessed questions.
     - **Option A2 (Filtered Batch Recovery)**: For completed original batch runs, preview `bisect-failed-batch --exam /path/to/exam.yaml --question Q21 --max-requests 39`. After reviewing current prices and obtaining explicit data/cost consent, supply the previewed `--revision` and `--confirm-cost`. Only confirmed filter errors are bisected; filtered singletons remain unscored for human review, and other errors stop. The limit excludes SDK retries. User edits and approvals are protected; reload the updated editor after recovery. See `references/grading.md`.
     - **Option B (Manual Review)**: After completion, grade failed items manually in `review-grading` / `review.xlsx` with no further API calls. For an incomplete run, `export-failed-review` creates a separate offline worksheet; its marks are not imported, and the web editor requires a completed run.
     - **Option C (Wait / Investigate)**: Wait for Azure quota reset before proceeding.

   **Semantic Answer Clustering (Optional, Before Review)**:
   - `cluster-answers --exam /private/exam.yaml [--threshold 0.82]` and
     `review-grading` default to cached/local lexical grouping without eager paid calls.
     `--confirm-cost` explicitly permits Azure embeddings; configuration comes from
     `exam.model_config` or an adjacent `config.yaml`, with a working-directory
     fallback if the selected file is missing; inspect the actual file using
     [configuration resolution](references/configuration.md#embedding-configuration-resolution).
     Endpoint-namespaced embedding
     caches remain private student data (details in `references/grading.md`).
   - In `review-grading`: use `Alt+S` for the All Questions Status dashboard, `📌 Grouped` to toggle answer grouping, `Ctrl+Enter` to confirm questions in batch, and `Alt+A` to approve only after 100% human review is complete (or use "Reset Review" to rollback if needed).

   **Post-Approval Reporting & Analytics Menu (Proactively Present to User)**:
   - Immediately after `grading/approval.json` is recorded (or whenever the user finishes reviewing), **always proactively present all post-approval options** so a general user knows what is available:
     1. **Standard Reports (`report`)** *(Offline, zero AI cost)*: Individual marked student PDFs, combined PDF, stratified audit samples, and score spreadsheets (`score_report.xlsx`, `details_score_report.xlsx`).
     2. **Offline Statistical Analytics (`analytics`)** *(Offline, zero AI cost)*: Cohort & class statistics (`statistics.xlsx`) and per-question box-plot PNGs.
     3. **AI Analysis & Advanced Reports**: `ai-analysis` is paid: preview, obtain
        explicit consent, review `ai-analysis/review.xlsx`, then `approve-analysis`.
        `advanced-report` defaults to offline Teacher DOCX/Class PPTX generation.
        Optional Azure infographics require a configured `models.analytics_image`
        deployment or override and explicit `--infographics --confirm-cost
        [--image-model DEPLOYMENT]`. For a separate image resource, read the
        [image configuration guide](references/configuration.md#separate-image-generation-resource)
        and pass `--image-model-config /private/image.config.yaml`.
        Copy the root [image template](../../../image-config.yaml.template) to a new
        private file; it uses `models.analytics_image`. Without that flag, the
        approved analysis manifest selects the configuration and Azure target.
        The standalone `azure-image-generation` skill uses a separate package
        and its own templates (`models.image`); do not conflate the workflows.
        Preserve prior reports with a fresh `--report-name reports-infographics`;
        do not edit the configuration bound to approved analysis. Preview first,
        then obtain separate data/cost consent and current manual image pricing.
        This path uses Azure Images API, not native Agent Framework image tools.
        Images are single-attempt, with text fallback; report failed images and
        never retry without a fresh user decision. Point users to the PPTX in the
        new named folder; the teacher DOCX remains text-only.
     4. **Moodle / LMS Export (`moodle-export`)** *(Offline, zero AI cost)*: Exports combined per-student PDFs (`student_pdfs/<ID>_<Name>.pdf` with AI feedback cover page + marked script), builds `recipients.csv` from a Moodle participants CSV, and (with `--worksheet`) fills a Moodle Assignment grading worksheet CSV + `feedback_files.zip` for bulk Moodle upload.
     5. **Email Distribution (`preview-email` -> `approve-email` -> `send-email`)**: Previews and emails marked PDFs and feedback to students (accepts `ID,EMAIL` or Moodle participants CSV directly).

   After grading and reporting are complete, always inform the user that results
   and review history have been preserved, and ask if they would like to clean
   or archive intermediate output using:
   `handwriting-grader clean --exam /path/to/exam.yaml`
   (creates a slim `.zip` backup by default, preserves HIL reviews, AI outputs, and final
   deliverables `reports/`, `analytics/`, `ai-analysis/`, `moodle/` while removing only
   bulky raw JPEGs and temp folders; pass `--full-archive` to include raw JPEGs in the `.zip`,
   and requires explicit `--confirm-delete`).
9. For distribution read `references/email.md`; never send without reviewing
   the exact preview and separate dispatch approval.
   For targeted regrading read `references/regrading.md`; require a current
   approved parent, separate cost consent and fresh review of the child.
10. If the requested next stage is unimplemented, stop and say so.

For the detailed stage flow and known notebook gaps read
`references/flow-and-parity.md`; for the short gate overview read
`references/workflow.md`. Ask for email details only when distribution is
requested; never send without explicit approval immediately before dispatch.
