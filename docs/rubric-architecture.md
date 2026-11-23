# Rubric Extraction, Verification & Approval Architecture

This document describes the schema, AI extraction, search-grounded verification, and cryptographic approval architecture for exam marking schemes in `azure-handwriting-grader-skills`.

---

## 1. Rubric Architecture & Excel Schema

A valid marking scheme is structured into an Excel workbook (`output/rubric/rubric.xlsx`) on sheet `Marking Scheme` with the following mandatory columns:

| Column Header | Type | Description |
| :--- | :--- | :--- |
| `question_number` | String/Int | Question key (e.g. `Q1`, `1a`, `Question 2`) |
| `question_text` | String | Full question text provided to students |
| `marking_scheme` | String | Detailed criteria, model answer, mark allocation rules |
| `marks` | Float/Int | Maximum marks allotted (must be finite, $> 0$) |

Validation rules (`rubric.py`):
- No empty question numbers or zero maximum marks.
- No formula cells (values must be evaluated text or numbers).
- Question numbers must resolve to unique keys via `question_key()`.

---

## 2. DOCX Extraction Pipeline (`extract-rubric`)

When a teacher supplies a Word document (`exam.marking_scheme: scheme.docx`), `extract-rubric` extracts questions and marks into structured Excel using Azure OpenAI:

1. **Extraction Pipeline**:
   - `mammoth` extracts raw text and tables from DOCX.
   - Sends criteria to Azure OpenAI using structured Pydantic response schema:
     ```python
     class RubricQuestion(BaseModel):
         question_number: StrictStr
         question_text: StrictStr
         marking_scheme: StrictStr
         marks: float
     ```
   - **Sub-Question Granularity**: The prompt requests separate individually marked sub-parts with combined labels and individual marks. Verify extraction manually; this is not a quality guarantee.
   - Writes `output/rubric/rubric.xlsx`.
2. **Safety Gate**:
   - Preview shows prompt shape and target model.
   - Requires explicit `--confirm-cost`.

---

## 3. Search-Grounded Verification (`verify-rubric`)

An optional verification stage uses Azure Responses hosted `web_search` (`verification.py`):
- Support depends on the Azure deployment and API version; unsupported requests can fail.
- The response parser extracts source links for human checking of model answers, formulas, dates and domain claims. Sources and claims may be incomplete or incorrect.
- Produces:
  - `output/rubric/verification/verification.xlsx`
  - `output/rubric/verification/verification.docx`
- **Important**: Verification output is strictly informational for the teacher; it does **not** constitute rubric approval.

Preview extraction/verification with `--model-config /private/config.yaml
--endpoint https://RESOURCE.openai.azure.com --api-version v1`; add
`--confirm-cost` only after separate data/cost consent. Calls use Azure SDK
Responses with `store=False`; verification is not cached.

---

## 4. Cryptographic Binding & Approval (`approve-rubric`)

Before grading can commence, a human teacher must explicitly review `rubric.xlsx` and run:
```bash
handwriting-grader approve-rubric --exam exam.yaml --confirm-reviewed
```

This generates `output/rubric/approval.json`:
```json
{
  "version": 1,
  "rubric_sha256": "3a7bd2...",
  "approved_at": "2026-11-20T10:20:00Z"
}
```

**Anti-Tampering Rule**: During grading, the SHA-256 hash of `output/rubric/rubric.xlsx` is recomputed. If any mark, criteria, or question text was modified without re-approval, the grading pipeline immediately halts.
