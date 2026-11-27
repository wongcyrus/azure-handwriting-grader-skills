# Region Definition, Layout Review & Suggestion Engine

This document describes the page layout coordinate system, AI bounding-box suggestion engine, browser-based editor, and region approval architecture in `azure-handwriting-grader-skills`.

---

## 1. Coordinate System & Geometry

Exam answer sheets use physical pixel bounding boxes anchored to rendered 200 DPI page images:
- Origin `(0, 0)` is at the top-left of the page image.
- Bounding Box Schema:
  ```json
  {
    "page": 0,
    "x": 120,
    "y": 340,
    "width": 1410,
    "height": 480
  }
  ```
- Mandatory Identification Boxes (Page 0):
  - `ID`: Student ID handwriting zone.
  - `CLASS`: Student Class handwriting zone.
  - `NAME`: Student Name handwriting zone.
- Question Boxes:
  - Labeled matching the approved rubric (e.g. `Q1`, `Q2`, `Q3`, ...).
  - Every question in the approved rubric must have exactly one bounding box across the page set.

---

## 2. Input Validation & Layout Preparation (`prepare-regions`)

1. Run offline `preflight` for input validation. There is no required scan-marker
   stage, heuristic orientation/order check or automatic page alignment.
2. `prepare-regions` reads `exam.scanned_pdf` and `layout.pages_per_student`.
3. Uses `render_pdf_to_images` (`pypdfium2`) to render the first script's $N$ pages into `output/regions/images/0.jpg`, `1.jpg`, etc.
4. Generates `output/regions/manifest.json` recording pixel dimensions `(width, height)` and SHA-256 hashes for each layout page.
5. Regions can be approved interactively in `review-regions` or headlessly after editing `annotations.json` via `handwriting-grader approve-regions --exam exam.yaml --confirm-reviewed`.

Review the first script's orientation, order and boxes. Newly rendered grading
images are preserved byte-for-byte, never automatically rotated, reordered or
aligned. Input, page-count, dimension and approval validation remains. Source
changes require a fresh output directory, preparation, review and approvals,
not silent regeneration of existing evidence.

After region confirmation, extract all students' metadata (ID/CLASS/NAME only),
without scanning or grading answers. Answers proceed automatically only when IDs
are nonempty, unique and exactly cover the expected PRESENT roster; preserve
leading zeroes without requiring scan order to match roster order. Otherwise
stop with exact 1-based source PDF page/script numbers in private
`grading/id-check.json`, an incomplete metadata checkpoint and no completed review
workbook. After source inspection and explicit new cost consent, resume may
re-extract missing/invalid saved metadata, bypass known-rejected cache and recheck
all IDs before answers. Metadata-first original-run recovery respects this gate;
child regrading retains current human-approved parent identity lineage and needs
fresh child identity/score review.
The diagnostic is not approval; teacher identity/score review remains mandatory
because roster consistency cannot establish identity correctness or other pages'
order/completeness.

---

## 3. Azure OpenAI Bounding Box Proposals (`suggest-regions`)

Teachers can request automated proposal boxes using Azure image-input deployment (`models.annotation`):
```bash
handwriting-grader suggest-regions --exam exam.yaml \
  --model-config config.yaml --endpoint https://RESOURCE.openai.azure.com --api-version v1 --confirm-cost
```
- **Approved-Rubric-First Requirement**: `suggest-regions` requires an extracted/imported and approved `output/rubric/rubric.xlsx` (`approve-rubric --confirm-reviewed`) and refuses to run if no question ID list exists.
- **Dynamic Prompt Injection**: `load_rubric_questions()` reads every `question_number` and a short text summary from `rubric.xlsx`, and `build_prompt()` injects them dynamically into the prompt (with zero hardcoded label examples). `question_ids` is included in the cache key so rubric changes invalidate stale suggestions.
- **Deployment**: Uses `models.annotation` (new-template candidate `gpt-6.1-terra`), requiring GPT-5+, image input and structured output. Spatial precision is not guaranteed; inspect every box. Preview without `--confirm-cost` first.
- Generates `output/regions/ai_suggestions.json`.
- **Safety Rule**: Suggestions are non-destructive proposals. They never automatically overwrite manual bounding boxes.

---

## 4. Browser-Based Region Editor (`review-regions`)

A zero-dependency local web server implemented in [`src/handwriting_grader/editor.py`](../src/handwriting_grader/editor.py):
- Binds strictly to `127.0.0.1` on a free ephemeral or user-selected port (`--port`).
- Enforces access control via a cryptographically random URL fragment token (`http://127.0.0.1:PORT/#TOKEN`).
- Prevents cross-origin attacks via strict `Origin` header validation.
- `/api/state` returns `expected_questions` from `rubric.xlsx` alongside page dimensions and draft annotations.
- Interactive UI (`editor.html`):
  - Zoom and pan scanned pages.
  - Auto-loads proposals from `ai_suggestions.json` (or via "Load AI suggestions").
  - **Live Missing-Box Warning**: Normalizes labels across all pages with `questionKey()` and displays an alert banner whenever `ID` on Page 1 or any expected rubric question is missing a bounding box.
  - Draw, drag, resize, and label boxes.
  - "Approve all regions" saves `annotations.json` and records cryptographic `approval.json`.
