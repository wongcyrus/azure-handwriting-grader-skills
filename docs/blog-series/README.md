# From paper exams to teacher-reviewed AI grading on Azure

Eight complete, output-led article drafts for Microsoft publishing review.
Prepared 24 November 2026 using the existing cleared example and saved reports.

## Read and publish

Open `index.html` for the article list. Each article has a Markdown master and a
rendered HTML version. For a rich-text blog editor, copy the rendered article
body, paste, then upload numbered images separately and check heading/code
formatting. Do not paste raw Learn-specific Markdown into a rich-text editor.
For Microsoft Learn's documentation pipeline, use Markdown and adapt image
syntax to that site's [authoring reference](https://learn.microsoft.com/en-us/contribute/content/markdown-reference).

The actual publishing platform and editorial requirements still need confirmation.
These are editorial drafts, not a claim of Microsoft acceptance or endorsement.

Banner exports are 1200 x 630 PNG with 2400 x 1260 JPEG layout masters. That is our working
recommendation, not a verified mandatory Microsoft banner dimension. Confirm the
destination editor's requirements and cropping. Keep in-body infographic artwork
separate from banners.

Each of the eight banners now uses a different AI-generated scene based on its
article's title and description, with varied palettes and left/right composition.
MVP, Azure OpenAI, Microsoft Foundry and Microsoft Agent Framework marks and
exact typography are composited locally.
[Brand provenance and publication caveats](branding/README.md) distinguish
official Azure icons from the two user-supplied third-party copies. The MVP
badge identifies the author, not Microsoft endorsement. Confirm asset permission
with the publishing editor before upload.
[Preview the eight AI-generated scenes](banner-prototypes/03-distinct-ai-artworks.jpg)
and [all eight finished banners](banner-prototypes/04-distinct-banners-preview.jpg).
The [actual generation prompts](branding/README.md) and original-image hashes
are included; exact PNG originals and private audits remain outside this package.

Each HTML file contains only the article, not this editorial guide. `ASSETS.csv`
lists every article image's filename, alt text and caption for uploading.
Image/table exports derived from workbook/JSON content are labelled accordingly;
they are not fabricated Excel or product screenshots.
`EVIDENCE-MAP.csv` maps each demonstrated step to its actual output and explicitly
identifies source-only procedures or outcomes that were not captured.

## Technical reading and prompt conventions

Each article now includes a self-contained technical walkthrough: relevant
production prompt templates or an explicit explanation that the operation is
local and has no LLM prompt, implementation code, data flow, validation and
interpretation of the observed outputs. Teacher/operator prompts are labelled
separately from application-generated model prompts. Template placeholders show
runtime insertion; they are not asserted historical HTTP payloads.

Every article also contains its **complete actual banner-generation prompt**,
the image API method, the generated scene before composition, exact local
typography/branding mechanics and its recorded estimate. No sidebar download is
needed to read the prompt. `branding/prompts/` retains the original briefs.

Part 6 includes a new real Framework execution with synthetic validation/grading
stubs and an explicitly forbidden Azure client, alongside its complete script
and captured output. It demonstrates typed sequencing without a paid grading
run or alteration of the example. It is not a historical exam event trace.

## Articles

1. [Your first teacher-reviewed AI marking run](01-first-marking-run.md)
2. [Review, correct and return results](02-review-and-return.md)
3. [Logic before AI](03-logic-and-recovery.md)
4. [Getting the image right](04-scans-crops-alignment.md)
5. [Inside Azure OpenAI multimodal grading](05-azure-openai.md)
6. [What Microsoft Agent Framework actually orchestrates](06-agent-framework.md)
7. [Check prices before AI](07-pricing-and-data.md)
8. [From demonstration to school pilot](08-pilot-and-outputs.md)

## Evidence and editorial caveats

- The actual dataset is four students, eight pages and five ten-mark questions.
  The owner confirmed that the current example PDFs are synthetic or cleared for
  public publication and requested retention of their details.
- Fresh read-only preflight passes. Fresh scan checking flags possible sequence
  problems on pages 1, 3 and 5. No repair or paid rerun was performed.
- Fresh review diagnostics report no discrepancies but explicitly retain the
  human-review/approval requirement. This is not approval validation for reporting.
- Historical version-1 reports retain index-only PDF names. Newer source naming
  behavior is explained but not misrepresented as an existing output.
- Saved OCR metadata includes a bad name/class extraction for John. Saved grades
  include clipped-answer warnings and flagged manual-review rows.
- Existing cost accounting under the grading folder includes later phases.
  Scope is explained rather than calling the accumulated total “grading cost.”
- Saved image-report manifests include both failures and a later successful
  folder. No grading or reporting rerun was performed. Eight separately
  authorized banner-art requests were completed, with no automatic retries and
  estimated total US$0.06394. This is separate from the original one-request
  prototype (estimated US$0.00713) and all grader/reporting costs.
- No local browser UI, child regrade, delivery preview, Moodle export, live price
  failure or framework event trace was captured. Those procedures are labelled
  as command/source examples, not claimed executions.
  The separately labelled offline synthetic Framework smoke test is new evidence,
  not a replay of that historical exam.

The source revision inspected was
`b6af53dd1cf4cf74b9a50591f0e775a3b1533133` in
[azure-handwriting-grader-skills](https://github.com/wongcyrus/azure-handwriting-grader-skills/tree/b6af53dd1cf4cf74b9a50591f0e775a3b1533133).
`sources.json` records local source hashes and selected evidence provenance.
`snippets/` includes exact relevant source excerpts. Add appropriate editorial
links to those pinned source files in the publishing editor.

The independent
[image-generation repository](https://github.com/wongcyrus/azure-image-generation-skills)
is a companion tool, not a grader dependency.

## What this package contains

`media/`: numbered output images and eight banners.
`masters/`: larger banner masters.
`branding/`: publication artwork, original marks and provenance.
`diagrams/`: editable Mermaid for explanatory diagrams, accompanied by PNGs.
`observed/`: selected read-only terminal outputs.
`snippets/`: source excerpts, not claimed historical request payloads.
`previews/`: actual Office document-to-PDF/PNG previews when available.

Private configurations, complete price/usage journals, resource endpoints,
credentials and review URLs are not copied into the article assets.

## Rebuild and validate

From `docs/blog-series/`, the build is offline after installing its own dependencies:

```bash
uv run --project tools python tools/build.py
uv run --project tools python tools/check_articles.py
```

It reads the containing Azure checkout, exports whitelisted
evidence, creates banners/diagrams locally and renders HTML. It never imports
the grader or calls Azure. Do not rerun paid workflows merely for a screenshot.
It refreshes only the explicitly marked banner-walkthrough sections of the
Markdown masters from retained prompts, images and provenance, then renders HTML.
The technical prose remains editorially authored; markers are not a new runtime
dependency or a skill instruction.
The second command checks complete inline prompt templates and Framework
functions against canonical source, banner-section freshness, and Python/JSON
block syntax without importing the grader or making model calls.
Review the articles and images before public upload; publication is not performed.
