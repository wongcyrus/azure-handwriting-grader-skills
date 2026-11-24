"""Build publication assets offline from selected existing evidence."""

import csv
import hashlib
import html
import json
from pathlib import Path
import re
import shutil
import textwrap

import markdown
from openpyxl import load_workbook
from PIL import Image, ImageDraw, ImageFont
import pypdfium2 as pdfium
from pptx import Presentation
from banners import build_banners, SOURCES as BANNER_SOURCES
from article_content import without_banner_appendix
from export_word import export_all_word
from svg_diagrams import build_all_diagrams


ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parents[1]
OUTPUT = REPO / "example/output"
MEDIA = ROOT / "media"
FONT_ROOT = Path("/usr/share/fonts/truetype/dejavu")
SOURCES = []
for folder in ("media", "masters", "diagrams", "observed", "snippets", "previews"):
    (ROOT / folder).mkdir(exist_ok=True)


def font(size, bold=False, mono=False):
    family = "DejaVuSansMono" if mono else "DejaVuSans"
    return ImageFont.truetype(str(FONT_ROOT / f"{family}{'-Bold' if bold else ''}.ttf"), size)


def record(path):
    relative = str(path.relative_to(REPO))
    if not any(item["path"] == relative for item in SOURCES):
        SOURCES.append({"path": relative, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()})
    return path


def data(name):
    return json.loads(record(OUTPUT / name).read_text(encoding="utf-8"))


def workbook(name, sheet):
    book = load_workbook(record(OUTPUT / name), read_only=True, data_only=True)
    rows = list(book[sheet].values)
    book.close()
    return rows


def wrapped(text, face, width):
    probe = ImageDraw.Draw(Image.new("RGB", (1, 1)))
    result = []
    for paragraph in str(text).splitlines() or [""]:
        line = ""
        for word in paragraph.split(" "):
            candidate = (line + " " + word).strip()
            if line and probe.textlength(candidate, font=face) > width:
                result.append(line)
                line = word
            else:
                line = candidate
        result.append(line)
    return result


def panel(filename, title, content, *, subtitle="Actual saved output excerpt", mono=False):
    face = font(21 if mono else 24, mono=mono)
    lines = []
    for line in content.splitlines():
        lines.extend(wrapped(line, face, 1060))
    line_h = 32 if mono else 35
    card_top = 126
    card_h = max(140, 48 + line_h * len(lines))
    total_h = card_top + card_h + 36
    image = Image.new("RGB", (1200, total_h), "#eef4fb")
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 0, 1200, 8), fill="#0078d4")
    draw.text((44, 28), title, font=font(30, bold=True), fill="#0f2942")
    draw.text((44, 72), subtitle, font=font(17), fill="#475569")
    if mono:
        draw.rounded_rectangle((44, card_top, 1156, card_top + card_h + 26), radius=14,
                               fill="#0f172a", outline="#334155", width=2)
        draw.rounded_rectangle((44, card_top, 1156, card_top + 38), radius=14, fill="#1e293b")
        draw.rectangle((44, card_top + 24, 1156, card_top + 38), fill="#1e293b")
        for idx, dot_color in enumerate(("#ef4444", "#f59e0b", "#10b981")):
            cx = 70 + idx * 22
            cy = card_top + 19
            draw.ellipse((cx - 6, cy - 6, cx + 6, cy + 6), fill=dot_color)
        for index, line in enumerate(lines):
            draw.text((70, card_top + 56 + index * line_h), line, font=face, fill="#e2e8f0")
    else:
        draw.rounded_rectangle((44, card_top, 1156, card_top + card_h), radius=14,
                               fill="#ffffff", outline="#cbd5e1", width=2)
        draw.rounded_rectangle((44, card_top, 52, card_top + card_h), radius=4, fill="#0078d4")
        for index, line in enumerate(lines):
            draw.text((74, card_top + 24 + index * line_h), line, font=face, fill="#1e293b")
    image.save(MEDIA / filename)


def table(filename, title, headers, rows, *, widths=None, subtitle="Actual workbook cells, rendered for the article"):
    widths = widths or [1112 // len(headers)] * len(headers)
    total_w = sum(widths)
    x0 = (1200 - total_w) // 2
    face = font(19)
    header_face = font(19, bold=True)
    line_height = 28
    layouts = []
    for row_idx, row in enumerate([headers, *rows]):
        active_face = header_face if row_idx == 0 else face
        cells = [wrapped("" if value is None else str(value), active_face, width - 24)
                 for value, width in zip(row, widths)]
        layouts.append((cells, max(len(cell) for cell in cells) * line_height + 24))
    total_h = 166 + sum(height for _, height in layouts)
    image = Image.new("RGB", (1200, total_h), "#f8fafc")
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 0, 1200, 8), fill="#0078d4")
    draw.text((x0, 28), title, font=font(30, bold=True), fill="#0f2942")
    draw.text((x0, 74), subtitle, font=font(17), fill="#475569")
    y = 122
    draw.rounded_rectangle((x0 - 2, y - 2, x0 + total_w + 2, y + sum(h for _, h in layouts) + 2),
                           radius=10, fill="#ffffff", outline="#cbd5e1", width=2)
    for index, (cells, height) in enumerate(layouts):
        x = x0
        row_fill = "#0f2942" if index == 0 else ("#f1f5f9" if index % 2 == 0 else "#ffffff")
        for col_idx, (cell, width) in enumerate(zip(cells, widths)):
            draw.rectangle((x, y, x + width, y + height), fill=row_fill, outline="#e2e8f0")
            active_face = header_face if index == 0 else face
            text_color = "#ffffff" if index == 0 else "#1e293b"
            for offset, line in enumerate(cell):
                draw.text((x + 12, y + 11 + offset * line_height), line,
                          font=active_face, fill=text_color)
            x += width
        y += height
    image.save(MEDIA / filename)


def pdf_page(source, filename, page_index=0):
    if source.is_relative_to(REPO):
        record(source)
    with pdfium.PdfDocument(source) as document:
        page = document[page_index]
        bitmap = page.render(scale=150 / 72)
        bitmap.to_pil().convert("RGB").save(MEDIA / filename)
        bitmap.close()
        page.close()


for name in BANNER_SOURCES:
    record(ROOT / "branding" / name)
build_banners()
banner_provenance = json.loads((ROOT / "branding/artwork-provenance.json").read_text())
artworks = banner_provenance["artworks"]
assert len(artworks) == 8 and len({item["original_png_sha256"] for item in artworks}) == 8
for item in artworks:
    for key, expected in (("publication_file", "publication_sha256"),
                          ("prompt_file", "submitted_prompt_sha256")):
        path = ROOT / "branding" / item[key]
        assert hashlib.sha256(path.read_bytes()).hexdigest() == item[expected], path

pdf_page(REPO / "example/VTC Test.pdf", "01-original-page.png")
pdf_page(OUTPUT / "reports/pdfs/script-00001.pdf", "09-marked-peter-page.png")
pdf_page(ROOT / "previews/teacher-report.pdf", "26-teacher-report-page.png")
pdf_page(ROOT / "previews/class-presentation.pdf", "27-class-chart-slide.png", page_index=1)

for name, filename, title in (
    ("preflight.txt", "02-preflight.png", "Preflight: actual terminal output"),
    ("check-scans.txt", "03-scan-check.png", "Scan check: actual blocking output"),
):
    panel(filename, title, (ROOT / "observed" / name).read_text(),
          subtitle="Read-only command captured 24 November 2026", mono=True)

rubric = workbook("rubric/rubric.xlsx", "Marking Scheme")
table("04-rubric.png", "Rubric: five questions, 50 possible marks",
      ["Question", "Question text (short excerpt)", "Maximum"],
      [[row[0], textwrap.shorten(row[1], width=115), row[3]] for row in rubric[1:]],
      widths=[150, 810, 160])

annotations = data("regions/annotations.json")
image = Image.open(record(OUTPUT / "regions/images/0.jpg")).convert("RGB")
draw = ImageDraw.Draw(image)
for box in annotations["0"]:
    x, y, w, h = (box[key] for key in ("x", "y", "width", "height"))
    draw.rectangle((x, y, x + w, y + h), outline="#d04a13", width=5)
    draw.rectangle((x, y - 25, x + 120, y), fill="#d04a13")
    draw.text((x + 4, y - 25), box["label"], font=font(20, bold=True), fill="white")
image.save(MEDIA / "05-region-overlay.png")

results = data("grading/results.json")
scores = workbook("reports/score_report.xlsx", "Marks")
john = next(item for item in results["scripts"] if item["script_index"] == 2)
table("06-identity-comparison.png", "Script index 2: raw OCR and saved report",
      ["Field", "Raw OCR in results.json", "Saved scorebook"],
      [["ID", john["id_ocr"], scores[3][0]], ["Name", john["name_ocr"], scores[3][1]],
       ["Class", john["class_ocr"], scores[3][2]]], widths=[160, 560, 400],
      subtitle="Comparison of actual artifacts; not a replay of review actions")
image = Image.open(record(OUTPUT / "grading/images/4.jpg")).convert("RGB")
box = next(box for box in annotations["0"] if box["label"] == "Q3")
x, y, w, h = (box[key] for key in ("x", "y", "width", "height"))
image.crop((x, y, x + w, y + h)).save(MEDIA / "07-john-q3-crop.png")
draw = ImageDraw.Draw(image)
draw.rectangle((x, y, x + w, y + h), outline="#d04a13", width=6)
image.save(MEDIA / "13-john-page.png")

reviews = workbook("grading/review.xlsx", "Marks")
review_objects = [dict(zip(reviews[0], row)) for row in reviews[1:]]
flagged = [item for item in review_objects if item["moderator_flag"]]
table("08-review-flags.png", "Flagged answer review: saved workbook fields",
      ["Script index", "Question", "Raw", "Manual", "Reviewed"],
      [[item[key] for key in ("script_index", "question", "raw_mark", "manual_mark", "reviewed")]
       for item in flagged], widths=[230, 230, 180, 230, 250])
table("10-scorebook.png", "Actual scorebook: four saved report rows", scores[0], scores[1:],
      widths=[200, 150, 100, 120, 550])

approval = data("grading/approval.json")
panel("12-approval-evidence.png", "Saved grading approval: selected fields",
      json.dumps({key: value[:16] + "..." if key.endswith("sha256") else value
                  for key, value in approval.items()}, indent=2),
      subtitle="Hash prefixes shortened; existence is not a fresh readiness check", mono=True)
grading_manifest = data("grading/manifest.json")
panel("14-grading-evidence.png", "Saved grading evidence",
      json.dumps({"grading_mode": grading_manifest["grading_mode"],
                  "aligned_to_regions": grading_manifest["aligned_to_regions"],
                  "completed": results["completed"], "scripts": len(results["scripts"]),
                  "mark_records": len(results["marks"]),
                  "checkpoint_version": results["checkpoint_version"]}, indent=2), mono=True)
mark = next(item for item in results["marks"] if item["script_index"] == 0 and item["question"] == "Q2")
panel("15-q2-result.png", "Peter / Q2: observed saved result",
      json.dumps({key: mark[key] for key in
                  ("answer", "raw_mark", "moderated_mark", "similarity_score", "reasoning", "moderator_flag")},
                 indent=2), mono=True)

def flow(filename, title, nodes, mermaid_name, mermaid):
    (ROOT / "diagrams" / mermaid_name).write_text(mermaid + "\n", encoding="utf-8")


build_all_diagrams(MEDIA)

flow("11-architecture.png", "Application boundaries (explanatory diagram)",
     ["Local exam, scans, roster and rubric", "Input checks + explicit human input approvals",
      "Cost consent + required-price verification", "Azure OpenAI -> draft results + usage evidence",
      "Separate teacher review + grading approval", "Local reports / analytics; separate distribution approval"],
     "architecture.mmd", """flowchart TD
  A[Local inputs] --> B[Input checks and human input approvals]
  B --> C[Cost consent and required-price verification]
  C --> D[Azure OpenAI]
  D --> E[Draft results and usage evidence]
  E --> F[Separate teacher review and grading approval]
  F --> G[Local reports and analytics]
  G --> H[Separate distribution approval]""")
flow("16-framework.png", "Microsoft Agent Framework: actual structure",
     ["ValidateApproval: approved_inputs()", "ExecuteGrading: asyncio.to_thread(grade_function, ...)",
      "RequireHumanReview: yield output path only", "OUTSIDE WORKFLOW: teacher review and explicit approval"],
     "framework.mmd", """flowchart TD
  A[ValidateApproval] --> B[ExecuteGrading]
  B --> C[RequireHumanReview: yield draft path]
  C -. separate operation .-> D[Teacher reviews]
  D --> E[Explicit application approval]""")
flow("17-pricing-gate.png", "Before a paid request",
     ["Preview intended work without inference", "Obtain explicit cost and data-transfer consent",
      "Verify required rates and configuration binding", "FAIL -> blocked; PASS -> authorized SDK request",
      "Record returned usage; unknown cost stays unknown"],
     "pricing.mmd", """flowchart TD
  A[Offline preview] --> B[Explicit cost and data consent]
  B --> C{Required prices verified?}
  C -->|No| D[Block; review evidence]
  C -->|Yes| E[Authorized SDK request]
  E --> F[Usage evidence and estimated cost]""")

price_rows = []
for folder in ("rubric", "regions", "grading", "ai-analysis"):
    path = record(OUTPUT / folder / "telemetry/azure_price_checks.jsonl")
    checks = [json.loads(line) for line in path.read_text().splitlines()]
    price_rows.append([folder, len(checks), ", ".join(sorted({item["kind"] for item in checks})),
                       ", ".join(sorted({item["source"]["verification"] for item in checks}))])
table("18-pricing-evidence.png", "Existing price journals: selected evidence",
      ["Stage", "Checks", "Operation kinds", "Evidence"], price_rows,
      widths=[280, 150, 330, 360], subtitle="Resource endpoints and deployment aliases excluded")
costs = data("grading/cost_summary.json")
table("19-cost-phases.png", "Stored cost summary spans multiple phases",
      ["Phase", "Logical calls", "Recorded USD"],
      [[key, value["calls"], f'{value["cost"]:.6f}' if value["cost"] is not None else "Unknown"]
       for key, value in costs["phases"].items()] +
      [["STORED TOTAL", costs["total_calls"], f'{costs["total_cost_usd"]:.6f}']],
      widths=[600, 220, 300],
      subtitle="Actual saved estimate; not grading-only and not an Azure invoice")

overall = workbook("analytics/statistics.xlsx", "Overall")
questions = workbook("analytics/statistics.xlsx", "Questions")
table("20-statistics.png", "Saved reviewed-score statistics",
      ["Measure", "Saved value"],
      [["Students", overall[1][0]], ["Mean / 50", overall[1][1]], ["Median / 50", overall[1][2]],
       ["Sample standard deviation", overall[1][3]], ["Minimum / maximum", f"{overall[1][4]} / {overall[1][5]}"],
       ["Pass policy", "Not configured"]] +
      [[f"{row[0]} mean / 10", row[2]] for row in questions[1:]], widths=[700, 420])
shutil.copyfile(record(OUTPUT / "analytics/question-boxplots-001.png"),
                MEDIA / "21-question-boxplots.png")
analysis = workbook("ai-analysis/review.xlsx", "Class")
text = analysis[1][0]
first = text.split("\n\n")[0]
note = next(line for line in text.splitlines() if "Evidence note:" in line)
panel("22-analysis-excerpt.png", "Saved class analysis: selected text",
      first + "\n\n" + note, subtitle="Actual reviewed-workbook text; Markdown markers retained")

office = OUTPUT / "ai-analysis/reports"
pres = Presentation(record(office / "class-presentation.pptx"))
record(office / "teacher-report.docx")
panel("23-office-outputs.png", "Existing offline Office report outputs",
      f"teacher-report.docx\nText-only teacher analysis report\n\n"
      f"class-presentation.pptx\n{len(pres.slides)} slides, including native editable chart\n\n"
      "Manifest: completed = true; infographics_count = 0",
      subtitle="Actual file/package inspection; not an Office UI screenshot")
attempt_rows = []
for folder in ("reports", "reports-infographics", "reports-infographics-v2"):
    manifest = data(f"ai-analysis/{folder}/manifest.json")
    attempt_rows.append([folder, manifest["infographics_count"], len(manifest["failed_infographics"])])
table("24-report-attempts.png", "Saved report attempts: failures remain visible",
      ["Folder", "Images", "Failures"], attempt_rows, widths=[760, 180, 180],
      subtitle="Actual saved manifests; not a reconstructed troubleshooting timeline")
with Image.open(record(OUTPUT / "ai-analysis/reports-infographics-v2/infographics/class.png")) as image:
    image = image.convert("RGB")
    image.thumbnail((1200, 1200), Image.Resampling.LANCZOS)
    image.save(MEDIA / "25-class-infographic.png", optimize=True)

snippet_ranges = {
    "workflow-source.py.txt": ("workflow.py", 1, None),
    "item-grade-source.py.txt": ("grading.py", 292, 338),
    "batch-grade-source.py.txt": ("grading.py", 340, 450),
    "azure-request-source.py.txt": ("azure_ai.py", 182, 232),
    "alignment-source.py.txt": ("alignment.py", 42, 105),
    "statistics-source.py.txt": ("analytics.py", 1, 40),
    "report-naming-source.py.txt": ("reporting.py", 1, 48),
    "rubric-source.py.txt": ("rubric.py", 20, 88),
    "region-prompt-source.py.txt": ("suggestions.py", 18, 45),
    "review-validation-source.py.txt": ("grade_review.py", 115, 204),
    "checkpoint-publication-source.py.txt": ("regions.py", 16, 48),
    "analysis-prompts-source.py.txt": ("advanced.py", 32, 70),
    "price-verifier-source.py.txt": ("pricing.py", 400, 500),
    "cost-arithmetic-source.py.txt": ("telemetry.py", 128, 175),
}
for target, (filename, start, end) in snippet_ranges.items():
    source = record(REPO / "src/handwriting_grader" / filename)
    lines = source.read_text().splitlines()
    excerpt = "\n".join(lines[start - 1:end]).rstrip()
    (ROOT / "snippets" / target).write_text(
        f"# Source: src/handwriting_grader/{filename}; lines {start}-{end or len(lines)}\n"
        "# Excerpt from inspected source, not a runnable standalone program.\n\n" + excerpt + "\n")

for name in ("snippets/banner-generate-source.py.txt", "snippets/offline-framework-smoke.py",
             "observed/offline-framework-smoke.txt"):
    record(ROOT / name)
record(REPO / "skills/handwriting-grading/SKILL.md")
record(REPO / "skills/handwriting-grading/references/workflow.md")

revision = "b6af53dd1cf4cf74b9a50591f0e775a3b1533133"
(ROOT / "sources.json").write_text(json.dumps({
    "repository": "wongcyrus/azure-handwriting-grader-skills", "revision": revision,
    "captured_date": "2026-11-24", "sources": SOURCES,
    "publication_permission": "Owner confirmed existing example details may be retained.",
    "paid_calls_for_article_preparation": 0,
    "banner_artwork_prior_paid_calls": 1,
    "banner_artwork_current_paid_calls": banner_provenance["logical_calls"],
    "banner_artwork_estimated_cost_usd": banner_provenance["estimated_total_cost_usd"],
    "banner_branding_paid_calls": 0,
    "image_tool_source_revision": "ee6c616cdeac43a9c97b0261049cb278fd5449b5",
    "skill_source_revision": "dc115d88c62b6639659ce127c745b21e2a6d1df4",
    "framework_demonstration": "Synthetic offline run; no historical exam trace or Azure clients.",
}, indent=2))

STYLE = """
body{max-width:960px;margin:40px auto;padding:0 24px;font:18px/1.65 system-ui,sans-serif;color:#152d44;overflow-wrap:anywhere}
h1,h2,h3{line-height:1.2;color:#092f53}h2{margin-top:2em}
img{max-width:100%;height:auto;border:1px solid #d9e3ed}pre{padding:18px;overflow:auto;background:#f1f5f9}
code{font-size:.87em}table{border-collapse:collapse;width:100%;font-size:.9em;display:block;overflow-x:auto}
td,th{border:1px solid #c9d6e4;padding:9px;text-align:left}th{background:#eaf1f8}
a{color:#0067b8}em{color:#4b6175}
"""
assets = []
articles = sorted(ROOT.glob("[0-9][0-9]-*.md"))
rendered_sources = {path.resolve() for path in articles + [ROOT / "README.md", ROOT / "branding/README.md"]}
for source in articles + [ROOT / "README.md", ROOT / "branding/README.md"]:
    text = source.read_text()
    if source in articles:
        updated = without_banner_appendix(text)
        if updated != text:
            source.write_text(updated, encoding="utf-8")
        text = updated
    converted = markdown.markdown(text, extensions=["fenced_code", "tables", "sane_lists"])

    def article_link(match):
        target = (source.parent / (match[1] + ".md")).resolve()
        return f'href="{match[1]}.html"' if target in rendered_sources else match[0]

    converted = re.sub(r'href="([^":#]+)\.md"', article_link, converted)
    converted = converted.replace('href="README.html"', 'href="index.html"')
    title_match = re.search(r"^# (.+)$", text, re.MULTILINE)
    title = title_match[1]
    target = ROOT / "index.html" if source == ROOT / "README.md" else source.with_suffix(".html")
    target.write_text(
        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        f"<title>{html.escape(title)}</title><style>{STYLE}</style></head>"
        f"<body><article>{converted}</article></body></html>", encoding="utf-8")
    if source in articles:
        image_pattern = r"!\[([^\]]*)\]\(([^)]+)\)(?:\s*\n\s*\n\*([^*]+)\*)?"
        for alt, path, caption in re.findall(image_pattern, text):
            assert alt and (ROOT / path).is_file(), (source.name, path)
            assets.append({"article": source.name, "file": path, "alt_text": alt,
                           "caption": caption or "Article banner"})
        words = len(re.findall(r"\b[\w'-]+\b", text))
        assert words >= 650, (source.name, words)
        print(f"{source.name}: {words} words")
with (ROOT / "ASSETS.csv").open("w", newline="", encoding="utf-8") as file:
    writer = csv.DictWriter(file, fieldnames=["article", "file", "alt_text", "caption"],
                            lineterminator="\n")
    writer.writeheader()
    writer.writerows(assets)

for path in MEDIA.glob("*.png"):
    with Image.open(path) as image:
        image.verify()
for index in range(1, 6):
    with Image.open(MEDIA / f"{index:02}-banner.png") as image:
        assert image.size == (1200, 630)
for path in [*ROOT.glob("*.html"), ROOT / "branding/README.html"]:
    for target in re.findall(r'(?:src|href)="([^"]+)"', path.read_text()):
        if ":" not in target and not target.startswith("#"):
            assert (path.parent / target.split("#")[0]).exists(), (path, target)
    assert "token=" not in path.read_text().lower()
assert len(articles) == 5
export_all_word(ROOT)
print(f"Verified five articles, {len(assets)} image placements, Word exports, all local links and PNGs.")
