# Reporting, Offline Analytics & AI Feedback Engine

This document describes the student grade slip generation, class scorebook compilation, offline statistical analytics, and multimodal AI analysis pipeline in `azure-handwriting-grader-skills`.

---

## 1. Grade Reports & Annotated PDFs (`report`)

Invoked via `handwriting-grader report --exam exam.yaml [--run CHILD_RUN]`:

### 1.1 Excel Scorebooks
- `output/reports/score_report.xlsx`: Master class grade sheet mapping each student to reviewed total marks and the assigned PDF path.
- `output/reports/details_score_report.xlsx`: Granular sheet containing `Answers` and `Reasoning` from human-reviewed marks, plus `AnswersRaw` and `ReasoningRaw` preserving model initial output for audit comparison.

### 1.2 Individual Scored PDFs
- Generates `output/reports/pdfs/<ID>_<NAME>_script-00001.pdf`, for example
  `001_One_script-00001.pdf`. IDs and names come from approved identities and the
  roster, not unreviewed OCR. Leading zeroes and Unicode names are preserved;
  unsafe characters are replaced and long components shortened. The script suffix
  prevents filename collisions. Scorebook paths and email attachments use these names.
- Existing version-1 reports retain their original index-only filenames and remain
  usable with PDF integrity checks. They are not automatically renamed.
- Each student's original scanned script is overlayed with teacher-approved question marks and total marks.
- `output/reports/all.pdf`: Concatenates all individual grade slips in script order mapped to reviewed identities for print batching.
- `output/reports/sampleOfN.pdf`: Ranked top/middle/bottom samples where cohort size permits; optional `sampleOfN_only_pass.pdf` requires explicit pass threshold/equality policy.

---

## 2. Offline Statistical Analytics (`analytics`)

A pure-Python offline computation engine (`analytics.py`) that makes zero network or model calls:

### 2.1 Statistical Calculations (`statistics.xlsx`)
- Mean, Median, Standard Deviation, Interquartile Range (IQR), Minimum, and Maximum scores.
- Per-question facility index (difficulty level) and discrimination index.
- Pass rates and counts based on explicit `reporting.pass_mark` policy.

### 2.2 Question Box Plots (`question-boxplots-*.png`)
- Generates publication-ready box plots using Matplotlib.
- Displays 1.5-IQR whiskers, median lines, and highlighted outlier points.
- Groups up to 20 questions per image for clear legibility.

---

## 3. AI Performance Analysis (`ai-analysis` & `approve-analysis`)

Generates draft pedagogical feedback using configured Azure analytics/student-feedback
deployments (`advanced.py`). Preview with `--model-config /private/config.yaml
--endpoint https://RESOURCE.openai.azure.com --api-version v1`; obtain data/cost
consent before `--confirm-cost`. No accuracy or pedagogical quality is guaranteed.
1. **Student Strengths & Weaknesses**:
   - Analyzes each student's question-by-question performance and drafts targeted next steps.
2. **Question Misconception Diagnosis**:
   - Compares high-scoring and low-scoring answer samples per question to identify common student misconceptions.
3. **Class-Wide Curriculum Review**:
   - Synthesizes class-level topics requiring re-teaching.
4. **Human Review Gate (`ai-analysis/review.xlsx`)**:
   - Every student feedback item and question analysis must be reviewed by the teacher and marked `reviewed = yes`.
   - Approved via `approve-analysis --confirm-reviewed`.

---

## 4. Advanced Office Reports (`advanced-report`)

1. **Teacher Report (`teacher-report.docx`)**:
   - Generates executive Word document with class overview, question breakdown, and individual student feedback.
2. **Class Presentation (`class-presentation.pptx`)**:
   - Generates PowerPoint presentation with native editable bar charts and slide-by-slide question breakdowns.

`advanced-report --exam /private/exam.yaml` is offline by default and requires
current analysis approval. Optional infographics require an Azure image deployment
in `models.analytics_image` (such as an alias for `gpt-image-2.5-flare`) or override:
`advanced-report --exam /private/exam.yaml --infographics --confirm-cost
[--image-model DEPLOYMENT]`. Image generation uses a separate Azure image API,
not a chat deployment. Retries are disabled; cached PNGs may be reused and failed
images use text-card fallback. Inspect `failed_infographics` in the report manifest,
disclose failures and never retry without a fresh user decision.
