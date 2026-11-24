# Agent skills for teacher-reviewed handwriting grading on Azure

Eight skill-led technical articles for Microsoft publishing review, explaining
the assistant's decisions, Python implementation, Azure prompts and real outputs.
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

The central subject is the **agent skill**, not a sequence of commands for the
teacher to memorize. Each article includes a relevant verbatim `SKILL.md` excerpt,
explains how the assistant chooses tools from intent and workspace state, and
distinguishes that behavior from Python validation and Framework execution.
Python excerpts are explained in terms of their inputs, branches, returned
objects and failure conditions; production prompts explain the purpose and limits
of their clauses rather than appearing as unexplained copy/paste blocks.

There are three instruction layers: teacher intent, reusable skill guidance, and
application-generated Azure task prompts. Framework's typed `"grade"` message is
control data, not a fourth model prompt. The inspected Framework module does not
load `SKILL.md`; the host assistant invokes the Python CLI, which selects the
default Framework runtime. Skill instructions alone do not enforce approval.

Illustrative teacher requests and expected skill-guided decisions are **not
captured agent conversations**. Actual screenshots/exports and console outputs
remain separately labelled. Template placeholders show runtime insertion; they
are not asserted historical HTTP payloads. The scan-check stop rule belongs to
skill-guided preparation; the inspected grading route does not automatically
rerun that check.

Banner-generation prompts, code and costs belong only to the editorial
[branding documentation](branding/README.md), not the eight grading articles.
The artwork and provenance are retained; removing the unrelated appendices
requires no new image request.

Part 6 includes a new real Framework execution with synthetic validation/grading
stubs and an explicitly forbidden Azure client, alongside its complete script
and captured output. It demonstrates typed sequencing without a paid grading
run or alteration of the example. It is not a historical exam event trace.

## Articles

1. [Designing an Agent Skill for Exam Grading: Architecture, Preflight, and Scan Consensus](01-first-marking-run.md)
2. [Human-in-the-Loop by Design: Rubrics, Blind Score Review, and Cryptographic Approvals](02-review-and-return.md)
3. [Cryptographic State Machines, Atomic Checkpoints, and Isolated Child Regrading](03-logic-and-recovery.md)
4. [Region Extraction, Localhost Review UI, and FFT Page Alignment](04-scans-crops-alignment.md)
5. [Multi-Role Azure OpenAI Routing, Multimodal Batching, and Adversarial Prompt Safety](05-azure-openai.md)
6. [Multi-Agent Orchestration: Skill Policy vs. Microsoft Agent Framework](06-agent-framework.md)
7. [Fail-Closed Cost Governance: Retail Price Verification, Token Math, and Caching](07-pricing-and-data.md)
8. [Post-Approval Outputs: Analytics, Office Reports, Moodle/Email Delivery, and Cleanup](08-pilot-and-outputs.md)

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
The skill excerpts were checked against the published
[`handwriting-grading` skill at dc115d8](https://github.com/wongcyrus/azure-handwriting-grader-skills/blob/dc115d88c62b6639659ce127c745b21e2a6d1df4/skills/handwriting-grading/SKILL.md).
Copilot registration syntax was checked against build 1.0.114's bundled
documentation. Other skill hosts can have different discovery/registration rules.

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
It removes retired managed banner appendices if present and renders the
editorially authored Markdown masters. It does not inject banner tutorials.
The second command checks inline prompt templates, full functions and the CLI
handoff against canonical source, verifies skill excerpts and appendix removal,
and parses Python/JSON blocks without importing the grader or making model calls.
Review the articles and images before public upload; publication is not performed.
