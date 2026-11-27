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
  pricing or quota probing, and refuses overwrite. For live read-only account,
  deployment and retail discovery, use `discover-foundry` as described below.
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

## Teacher output index

Maintain a teacher-friendly `index.html` in the configured `exam.output_dir`.
It must open locally in a normal browser without a server or internet connection,
with readable headings, plain-language descriptions and clickable links.
This is an assistant-maintained guide, not an automatically generated CLI artifact
and not an approval record. Once the output directory exists, create or refresh it
when resuming a workspace and after every stage that creates, changes, fails to
create, archives, or removes useful outputs. Refresh it before presenting the
stage outcome, link to it in the response, and tell the teacher they can open it
in a browser. If the index cannot be written, say so and provide the relevant
output links directly; do not hide stage failures.

- Inspect actual files, completion manifests, and current hash-bound approvals
  before describing their status. A file's presence or a completed manifest
  alone is not proof of approval, current inputs, correctness, or permission to
  share. Mark partial, failed, stale, unverified, superseded, or unavailable
  results clearly; do not link absent files or claim that future outputs exist.
- Start with recommended current deliverables, then group other useful outputs by
  stage. Give each existing relative link a short plain-language description,
  its purpose, any necessary review or sharing warning, and relevant version or
  run context. Include review workbooks, reports, analytics, advanced decks,
  distribution previews/exports and cost summaries when present. Distinguish
  alternative, failed, manually modified, and child-run artifacts rather than
  implying they are current or automatically synchronized.
- Link folders for collections such as individual PDFs; do not enumerate student
  names, IDs, answers, feedback, credentials, or confidential content in the
  index. Treat the index and linked files as private. Explain that AI-generated
  images and analysis need human verification before sharing.
- Use relative HTML links rooted at the index location, URL-encode path components
  and escape HTML text and attributes. Keep the page self-contained, keyboard
  accessible, and free of external resources and scripts. Maintain only the
  clearly delimited `<!-- handwriting-grading:index:start -->` and
  `<!-- handwriting-grading:index:end -->` section, preserving user content
  outside it. Create a new index if none exists. If an existing index lacks a
  single unambiguous managed section, do not overwrite it; ask before modifying
  it or creating an alternate index. Never modify underlying outputs, approvals,
  or manifests just to update the index. If a previous assistant-managed Markdown
  index exists, preserve user content outside its managed section and mark that
  section as superseded with a link to the HTML page; do not alter an unmanaged
  Markdown file.
- Recheck and update links after a confirmed cleanup or archive. Do not start a
  paid request, retry, email, cleanup, or any other gated operation to build the
  index. Index maintenance does not replace the required user confirmations.

## Prepare an exam

1. Establish whether the user is starting or resuming, what stage they need,
   and which local paths they intend to use. Do not copy or overwrite data.
   First inspect existing exam and model configurations, approvals and available
   session context. Reuse verified values and existing stage selections; do not
   ask the user to repeat them or reconfirm them just because another stage starts.
   Offline preparation and review do not require a complete Azure profile. When
   live discovery is needed and the account is not already known, ask for the
   Foundry account name or account/project ARM resource ID. With the user's
   Azure sign-in, run read-only `discover-foundry --resource NAME`
   to retrieve the endpoint, resource region, deployed aliases, model versions,
   SKUs and supported retail prices. Ask only for unresolved choices needed for
   the requested stage, such as selecting between text deployments or an
   ambiguous retail profile. Propose the existing valid deployment for the stage
   instead of asking the user to choose again. Defer optional embeddings and
   image generation until requested; an image deployment may use a different
   Foundry resource and region, so discover that resource when needed. A project's
   name alone is not an account name;
   use its full ARM resource ID. If access or discovery fails, explain the error
   and offer manual configuration instead of repeatedly asking for every field.
   Review results and explicitly select any alternate retail meter region; do not
   infer it from the resource region or silently substitute it. Save only to a new
   private configuration, never rewrite an approved configuration. Discovery
   does not verify deployment capabilities, quota, quality, invoice prices, or
   permission to send data; every paid stage still requires its own preview and
   `--confirm-cost`.
   When resuming an existing workspace or `output_dir`, inspect existing files
   and artifacts to orient immediately (do not rely on prior conversation history):

   Treat this table as orientation, not proof of completion. Validate approvals
   and their bound inputs before choosing a next stage; artifact presence alone
   is insufficient. If an approval exists but `regions/images/` or
   `grading/images/` is missing, stop and explain that validation may fail.
   Ask before restoring the exact files from a verified backup; do not silently
   regenerate, replace, or reapprove them.

   | Artifact / Status | Possible Stage | Next Command / Action |
   |---|---|---|
   | No `exam.yaml` / `config.yaml` | Not configured | Configure `exam.yaml` and, when needed, `discover-foundry` -> `preflight` -> prepare and approve scan markers -> `check-scans` |
   | `exam.yaml` exists (no `rubric/` or `attendance/`) | Configured | `preflight` -> prepare and approve scan markers -> `check-scans` -> `prepare-attendance` (if configured) or `extract-rubric`/`import-rubric` |
   | No `scan-markers/approval.json` | Printed scan markers not approved | Preview `suggest-scan-markers` with explicit cost/data consent before paid calls -> teacher reviews markers and first-script order -> `approve-scan-markers` -> paid Azure `check-scans` before region setup or grading |
   | `attendance/current.json` points to a version without `approval.json` | Attendance prepared | Teacher reviews `attendance/versions/<review_id>/attendance_review.xlsx` -> `approve-attendance` |
   | `rubric/rubric.xlsx` (no `rubric/approval.json`) | Rubric extracted/imported | Teacher reviews `rubric/rubric.xlsx` -> `approve-rubric` |
   | `rubric/approval.json` (no `regions/approval.json` or `regions/images/`) | Rubric approved; region setup not completed | `prepare-regions` -> optional paid `suggest-regions` -> `review-regions`; if an existing region or grading approval references missing images, use the recovery guidance above instead |
   | `regions/images/` (no `regions/ai_suggestions.json`, no `regions/approval.json`) | Region pages rendered | Optional `suggest-regions` (preview and consent first), or local manual `review-regions` |
   | `regions/ai_suggestions.json` or `regions/draft.json` (no `regions/approval.json`) | Regions suggested/drafted | `review-regions` (adjust boxes & approve) or `approve-regions` |
   | `regions/approval.json` (no `grading/`) | Regions approved | `grade` (preview first, then `--confirm-cost`) |
   | `grading/checkpoint.json` (no `grading/manifest.json`) | Grading interrupted | `resume-grading` (preview first, then `--confirm-cost`) |
   | `grading/manifest.json`, `results.json` with `completed: false` | Grading interrupted | `resume-grading` (preview first, then `--confirm-cost`) |
   | `grading/manifest.json`, `results.json` with `completed: true` (no `grading/approval.json`) | Grading done (or failed items) | `cluster-answers` (optional) -> `review-grading` (or `retry-grading` if failures) -> approve |
   | `grading/approval.json` | Scores approved | Present Post-Approval Menu: `report`, `analytics`, `ai-analysis` (optional) |
   | `reports/manifest.json` or `analytics/manifest.json` | Reports / offline stats generated | Offer remaining options: `analytics`/`report` (if missing), `ai-analysis` -> `advanced-report`, `moodle-export` (LMS PDFs/ZIP/CSV), `preview-email` -> `send-email`, or `clean` |
   | `ai-analysis/review.xlsx` (no `ai-analysis/approval.json`) | AI analysis generated | Teacher reviews `ai-analysis/review.xlsx` -> `approve-analysis` |
   | `ai-analysis/approval.json` | AI analysis approved | Offer `advanced-report` with or without optional paid infographics, `preview-email` -> `send-email`, or `clean` |
   | `email/` preview artifact (no `email/approval.json`) | Email preview generated | Teacher inspects preview -> `approve-email` -> `send-email` |
   | `runs/<child>/` directory | Targeted single-question regrade | Inspect artifacts inside `runs/<child>/` and pass `--run <child>` to commands |

2. Read `references/configuration.md` and examine existing settings. Present
   relevant detected values; ask only for missing or ambiguous decisions needed
   for the current stage, grouping related choices when practical. Keep actual
   configuration outside version control:
   a. Exam settings (`exam.yaml`): define roster, scans, layout, attendance, and reporting.
   b. AI model configuration (`config.yaml`): inspect existing configurations
      rather than overwriting them. Prefer `discover-foundry` to generate a new
      configuration after reviewing its deployment and price results. For manual
      setup, generate separate templates with
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
   script numbers. A completed confirmation is retained even when it reports
   issues, and source changes invalidate marker approval. Preserve the existing
   output, correct the physical scan or source PDF, and prepare a new output
   directory with fresh marker review and separately consented scan checking.
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
   - For current Azure prices, read `references/pricing.md`. Use discovered resource
     location and deployment type where available; identify the retail meter
     region/profile explicitly and never infer it from an endpoint. Preview public retail rates
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
     - **Option A (Targeted Retry)**: For incomplete batch runs without review workbooks, preview `handwriting-grader retry-failed-batches --exam /path/to/exam.yaml`; for other runs preview `retry-grading`. Existing teacher edits are preserved; affected identities and marks require fresh review even if retry is interrupted. Do not edit the workbook while retry is running. Obtain cost consent before `--confirm-cost`. The batch retry stops on the first failure and does not resume unprocessed questions.
     - **Option A2 (Filtered Batch Recovery)**: For completed original batch runs, preview `bisect-failed-batch --exam /path/to/exam.yaml --question Q21 --max-requests 39`. After reviewing current prices and obtaining explicit data/cost consent, supply the previewed `--revision` and `--confirm-cost`. Only confirmed filter errors are bisected; filtered singletons remain unscored for human review, and other errors stop. The limit excludes SDK retries. User edits and approvals are protected; reload the updated editor after recovery. See `references/grading.md`.
     - **Option B (Manual Review)**: After completion, grade failed items manually in `review-grading` / `review.xlsx` with no further API calls. For an incomplete run, `export-failed-review` creates a separate offline worksheet; its marks are not imported, and the web editor requires a completed run.
     - **Option C (Wait / Investigate)**: Wait for Azure quota reset before proceeding.

   **Semantic Answer Clustering (Optional, Before Review)**:
   - `cluster-answers --exam /private/exam.yaml [--threshold 0.82]` and
     `review-grading` default to cached/local lexical grouping without eager paid calls.
     For paid clustering, use `--model-config /private/embedding.yaml` if the
     embedding deployment is configured separately. Run `--preview-embedding`,
     present the target, text, request bound, cache policy and verified price,
     then obtain explicit data/cost consent and pass `--confirm-cost --revision`
     with the exact preview revision. Existing `clusters.json` is not overwritten.
     Without an override, configuration comes from `exam.model_config` or an
     adjacent `config.yaml`, with a working-directory fallback if missing; inspect
     the actual file using
     [configuration resolution](references/configuration.md#embedding-configuration-resolution).
     Caching is disabled unless explicitly enabled; shared caches additionally
     require an explicit shared directory. Caches contain private student data.
   - In `review-grading`: use `Alt+S` for the All Questions Status dashboard, `📌 Grouped` to toggle answer grouping, `Ctrl+Enter` to confirm questions in batch, and `Alt+A` to approve only after 100% human review is complete (or use "Reset Review" to rollback if needed).

   **Post-Approval Reporting & Analytics Menu (Proactively Present to User)**:
   - Immediately after `grading/approval.json` is recorded (or whenever the user finishes reviewing), **always proactively present all post-approval options** so a general user knows what is available:
     1. **Standard Reports (`report`)** *(Offline, zero AI cost)*: Individual marked student PDFs, combined PDF, stratified audit samples, and score spreadsheets (`score_report.xlsx`, `details_score_report.xlsx`).
     2. **Offline Statistical Analytics (`analytics`)** *(Offline, zero AI cost)*: Cohort & class statistics (`statistics.xlsx`) and per-question box-plot PNGs.
     3. **AI Analysis & Advanced Reports**: `ai-analysis` is paid: preview, obtain
        explicit consent, review `ai-analysis/review.xlsx`, then `approve-analysis`.
        When offering or requesting advanced reports, explicitly offer both offline
        Teacher DOCX/Class PPTX and the optional paid Azure infographics for the
        PPTX. Before running `advanced-report`, ask which the user wants if their
        choice is not already clear; do not silently select the offline default or
        repeat a clear choice for the same report. The teacher DOCX remains text-only.
        Infographics require a configured `models.analytics_image`
        deployment or override and explicit `--infographics --confirm-cost
        [--image-model DEPLOYMENT]`. For a separate image resource, read the
        [image configuration guide](references/configuration.md#separate-image-generation-resource)
        and pass `--image-model-config /private/image.config.yaml`.
        Copy the root [image template](../../../image-config.yaml.template) to a new
        private file; it uses `models.analytics_image`. Without that flag, the
        approved analysis manifest selects the configuration and Azure target.
        The standalone `azure-image-generation` skill uses a separate package
        and its own templates (`models.image`); do not conflate the workflows.
        If an offline report already exists, offer to create an infographic version
        separately. Preserve prior reports with a fresh `--report-name reports-infographics`;
        do not edit the configuration bound to approved analysis. Preview first,
        then obtain separate data/cost consent and current manual image pricing.
        This path uses Azure Images API, not native Agent Framework image tools.
        Include each available infographic in the PPTX on a separate slide following
        its editable analysis and reviewed-score summary, with a visible warning that
        image text and numbers can be inaccurate or sample-based. Retain the editable
        slide when an image fails. Images are single-attempt; report failures and never
        retry without a fresh user decision. Review both analysis and images before
        sharing. Point users to the PPTX in the new named folder; the teacher DOCX
        remains text-only.
     4. **Moodle / LMS Export (`moodle-export`)** *(Offline, zero AI cost)*: Exports combined per-student PDFs (`student_pdfs/<ID>_<Name>.pdf` with AI feedback cover page + marked script), builds `recipients.csv` from a Moodle participants CSV, and (with `--worksheet`) fills a Moodle Assignment grading worksheet CSV + `feedback_files.zip` for bulk Moodle upload.
     5. **Email Distribution (`preview-email` -> `approve-email` -> `send-email`)**: Previews and emails marked PDFs and feedback to students (accepts `ID,EMAIL` or Moodle participants CSV directly).

   After grading and reporting are complete, always inform the user that results
   and review history have been preserved, and ask if they would like to clean
   or archive intermediate output using:
   `handwriting-grader clean --exam /path/to/exam.yaml`
   (creates a slim `.zip` backup by default, preserving grading and region images,
   reviews, approvals, and reports; removes only top-level `.grading-*` and
   `model-cache` data. `--full-archive` also includes those temporary/cache files.
   `--purge-reports` deletes all selected output, including an entire selected
   child run; it creates a full backup by default. Review the exact preview and
   obtain explicit authorization before `--confirm-delete`).
9. For distribution read `references/email.md`; never send without reviewing
   the exact preview and separate dispatch approval.
   For targeted regrading read `references/regrading.md`; require a current
   approved parent, separate cost consent and fresh review of the child.
10. If the requested next stage is unimplemented, stop and say so.

For the detailed stage flow and known notebook gaps read
`references/flow-and-parity.md`; for the short gate overview read
`references/workflow.md`. Ask for email details only when distribution is
requested; never send without explicit approval immediately before dispatch.
