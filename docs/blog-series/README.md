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

All eight now use the approved editorial artwork with locally composited MVP,
Azure OpenAI, Microsoft Foundry and Microsoft Agent Framework marks.
[Brand provenance and publication caveats](branding/README.md) distinguish
official Azure icons from the two user-supplied third-party copies. The MVP
badge identifies the author, not Microsoft endorsement. Confirm asset permission
with the publishing editor before upload.
[Preview all eight branded banners](banner-prototypes/02-branded-series-preview.jpg).

Each HTML file contains only the article, not this editorial guide. `ASSETS.csv`
lists every article image's filename, alt text and caption for uploading.
Image/table exports derived from workbook/JSON content are labelled accordingly;
they are not fabricated Excel or product screenshots.
`EVIDENCE-MAP.csv` maps each demonstrated step to its actual output and explicitly
identifies source-only procedures or outcomes that were not captured.

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
  folder. No grading or reporting rerun was performed. The editorial banner
  artwork reuses one previously approved paid prototype; this branding update
  makes no new model requests.
- No local browser UI, child regrade, delivery preview, Moodle export, live price
  failure or framework event trace was captured. Those procedures are labelled
  as command/source examples, not claimed executions.

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
```

It reads the containing Azure checkout, exports whitelisted
evidence, creates banners/diagrams locally and renders HTML. It never imports
the grader or calls Azure. Do not rerun paid workflows merely for a screenshot.
Review the articles and images before public upload; publication is not performed.
