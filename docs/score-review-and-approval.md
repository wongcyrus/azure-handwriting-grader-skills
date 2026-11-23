# Score Review, Human Approval & Discrepancy Diagnostics

This document details the teacher score review workflow, blind question marksheets, discrepancy diagnostics, and cryptographic grade approval architecture in `azure-handwriting-grader-skills`.

---

## 1. Human Review Philosophy: Teachers in the Loop

AI grades and moderation suggestions are strictly preliminary. Educational standards require that an authorized human instructor inspect, adjust, and approve all evaluations.

### The Double-Review Structure (`review.xlsx`):
1. **`Scripts` Sheet**:
   - `script_index`, `id_ocr`, `class_ocr`, `reviewed_id`, `reviewed`, `name_ocr`.
   - Requires matching every OCR identity against the enrolled roster and setting `reviewed = "yes"`.
2. **`Marks` Sheet**:
   - `script_index`, `question`, `page_image`, `answer`, `raw_mark`, `moderated_mark`, `reasoning`, `moderator_flag`, `moderator_note`, `grading_failed`, `manual_mark`, `reviewed`, `similarity_score`.
   - Any question with `grading_failed=True`, `moderator_flag=True`, or teacher text modifications requires an explicit `manual_mark`.
   - Every single row must have `reviewed = "yes"`.

---

## 2. Interactive Blind Score Editor (`review-grading`)

Implemented in [`src/handwriting_grader/score_editor.py`](../src/handwriting_grader/score_editor.py):

- **Blind Marking Mode**:
  - Hides student names and IDs during question evaluation to prevent teacher unconscious bias.
- **Answer Grouping & Sorting**:
  - Defaults to cached/local lexical answer grouping. Explicit `--confirm-cost` permits paid Azure embeddings, resolved from `exam.model_config` or adjacent `config.yaml`; opening the editor does not eagerly call Azure. The grade similarity score is advisory and distinct from grouping.
  - Sorts by `Mark`, `Similarity`, `Script`, or `Status`.
- **Dynamic Crop Controls**:
  - **Expand Box**: Expands bounding box margins on the fly if a student wrote outside the lines.
  - **Full Page Modal**: Opens full scanned page to inspect context or cross-page overflow.
- **Inline Editing**:
  - Direct edits to answers, marks, and feedback notes.
- **Review History Vault**:
  - Every save automatically writes a private historical snapshot to `output/grading/review-history/review_YYYYMMDD_HHMMSS.xlsx`.

---

## 3. Discrepancy Diagnostics (`check-grading-review`)

A fast, read-only diagnostic utility (`review_diagnostics.py`):
```bash
handwriting-grader check-grading-review --exam exam.yaml [--run CHILD_RUN]
```

Checks:
- Unreviewed rows or missing `reviewed = yes`.
- Missing manual marks on flagged or failed items.
- Duplicate student IDs or IDs not found in the approved attendance roster.
- Marks outside allowed range $[0, \text{max\_marks}]$.
- Discrepancy between OCR class and enrolled class.

---

## 4. Cryptographic Grade Approval (`approve-grading`)

```bash
handwriting-grader approve-grading --exam exam.yaml --confirm-reviewed [--run CHILD_RUN]
```

Validates:
- Every script and question is reviewed.
- Re-hashes inputs: `model_config`, `roster`, `rubric.xlsx`, `regions/approval.json`, and `review.xlsx`.
- Writes `output/grading/approval.json`:
  ```json
  {
    "version": 1,
    "review_sha256": "81f2...",
    "manifest_sha256": "b4e1...",
    "approved_at": "2026-11-20T22:30:00Z"
  }
  ```
- **Anti-Tampering Rule**: Reporting commands (`report`, `analytics`, `ai-analysis`) verify `approval.json`. If `review.xlsx` is altered after approval, reports refuse to generate.

All identities, diagrams, transcriptions and reasoning still need human review.
Grouped-image comparisons do not guarantee whole-cohort consistency. Crop expansion
is a visual preview, not a saved paid regrade; follow separately reviewed child crop
proposals for changes. Local hash-bound approvals and history are not tamper-proof.
