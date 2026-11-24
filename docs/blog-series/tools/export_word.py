"""Export each blog Markdown article to a clean, copy-ready Microsoft Word (.docx) file."""

from pathlib import Path
import re

from docx import Document
from docx.oxml import OxmlElement, parse_xml
from docx.oxml.ns import nsdecls, qn
from docx.shared import Inches, Pt, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH


NAVY = RGBColor(0x0F, 0x29, 0x42)
BLUE = RGBColor(0x00, 0x67, 0xB8)
SLATE = RGBColor(0x47, 0x55, 0x69)
BODY = RGBColor(0x1E, 0x29, 0x3B)


def _shade_paragraph(paragraph, hex_color="F1F5F9"):
    p_pr = paragraph._p.get_or_add_pPr()
    shd = parse_xml(f'<w:shd {nsdecls("w")} w:fill="{hex_color}"/>')
    p_pr.append(shd)
    p_bdr = parse_xml(
        f'<w:pBdr {nsdecls("w")}>'
        '<w:left w:val="single" w:sz="12" w:space="6" w:color="0078D4"/>'
        "</w:pBdr>"
    )
    p_pr.append(p_bdr)


def _shade_cell(cell, hex_color):
    tc_pr = cell._tc.get_or_add_tcPr()
    shd = parse_xml(f'<w:shd {nsdecls("w")} w:fill="{hex_color}"/>')
    tc_pr.append(shd)


def _add_hyperlink(paragraph, text, url):
    part = paragraph.part
    r_id = part.relate_to(
        url,
        "http://schemas.openxmlformats.org/officeDocument/2006/relationships/hyperlink",
        is_external=True,
    )
    hyperlink = OxmlElement("w:hyperlink")
    hyperlink.set(qn("r:id"), r_id)
    new_run = OxmlElement("w:r")
    r_pr = OxmlElement("w:rPr")
    c = OxmlElement("w:color")
    c.set(qn("w:val"), "0067B8")
    u = OxmlElement("w:u")
    u.set(qn("w:val"), "single")
    r_pr.append(c)
    r_pr.append(u)
    new_run.append(r_pr)
    t = OxmlElement("w:t")
    t.text = text
    new_run.append(t)
    hyperlink.append(new_run)
    paragraph._p.append(hyperlink)


INLINE_RE = re.compile(
    r"(`[^`]+`|\*\*[^*]+\*\*|\*[^*]+\*|\[[^\]]+\]\([^)]+\))"
)


def _add_inline(paragraph, text, *, default_color=BODY, italic=False):
    pos = 0
    for match in INLINE_RE.finditer(text):
        if match.start() > pos:
            r = paragraph.add_run(text[pos:match.start()])
            r.font.color.rgb = default_color
            r.italic = italic
        token = match.group(0)
        if token.startswith("`") and token.endswith("`"):
            r = paragraph.add_run(token[1:-1])
            r.font.name = "Consolas"
            r.font.size = Pt(10)
            r.font.color.rgb = RGBColor(0x0F, 0x17, 0x2A)
        elif token.startswith("**") and token.endswith("**"):
            r = paragraph.add_run(token[2:-2])
            r.bold = True
            r.italic = italic
            r.font.color.rgb = default_color
        elif token.startswith("*") and token.endswith("*"):
            r = paragraph.add_run(token[1:-1])
            r.italic = True
            r.font.color.rgb = default_color
        elif token.startswith("["):
            m = re.match(r"\[([^\]]+)\]\(([^)]+)\)", token)
            if m:
                label, url = m.group(1), m.group(2)
                if url.startswith(("http://", "https://")):
                    _add_hyperlink(paragraph, label, url)
                else:
                    r = paragraph.add_run(label)
                    r.font.color.rgb = BLUE
        pos = match.end()
    if pos < len(text):
        r = paragraph.add_run(text[pos:])
        r.font.color.rgb = default_color
        r.italic = italic


def export_markdown_to_docx(md_path: Path, docx_path: Path, base_dir: Path):
    doc = Document()
    section = doc.sections[0]
    section.top_margin = Inches(0.8)
    section.bottom_margin = Inches(0.8)
    section.left_margin = Inches(0.85)
    section.right_margin = Inches(0.85)

    normal = doc.styles["Normal"]
    normal.font.name = "Segoe UI"
    normal.font.size = Pt(11)
    normal.font.color.rgb = BODY

    lines = md_path.read_text(encoding="utf-8").splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        if not stripped:
            i += 1
            continue

        # Fenced code block
        if stripped.startswith("```"):
            lang = stripped[3:].strip()
            code_lines = []
            i += 1
            while i < len(lines) and not lines[i].strip().startswith("```"):
                code_lines.append(lines[i])
                i += 1
            i += 1
            p = doc.add_paragraph()
            p.paragraph_format.space_before = Pt(4)
            p.paragraph_format.space_after = Pt(6)
            _shade_paragraph(p, "F1F5F9")
            r = p.add_run("\n".join(code_lines))
            r.font.name = "Consolas"
            r.font.size = Pt(9.5)
            r.font.color.rgb = RGBColor(0x0F, 0x17, 0x2A)
            continue

        # Image: ![alt](path)
        img_match = re.match(r"^!\[([^\]]*)\]\(([^)]+)\)$", stripped)
        if img_match:
            img_rel = img_match.group(2)
            img_path = (base_dir / img_rel).resolve()
            if img_path.is_file():
                p = doc.add_paragraph()
                p.alignment = WD_ALIGN_PARAGRAPH.CENTER
                p.paragraph_format.space_before = Pt(6)
                p.paragraph_format.space_after = Pt(2)
                p.add_run().add_picture(str(img_path), width=Inches(6.2))
            i += 1
            continue

        # Markdown table
        if stripped.startswith("|") and i + 1 < len(lines) and re.match(r"^\|[\s|:-]+\|$", lines[i + 1].strip()):
            table_lines = [stripped]
            i += 2
            while i < len(lines) and lines[i].strip().startswith("|"):
                table_lines.append(lines[i].strip())
                i += 1
            rows = [[cell.strip() for cell in row.strip("|").split("|")] for row in table_lines]
            cols = len(rows[0])
            tbl = doc.add_table(rows=len(rows), cols=cols)
            tbl.style = "Table Grid"
            for r_idx, row_vals in enumerate(rows):
                for c_idx in range(min(cols, len(row_vals))):
                    cell = tbl.cell(r_idx, c_idx)
                    cell.text = ""
                    p = cell.paragraphs[0]
                    p.paragraph_format.space_before = Pt(3)
                    p.paragraph_format.space_after = Pt(3)
                    if r_idx == 0:
                        _shade_cell(cell, "0F2942")
                        run = p.add_run(row_vals[c_idx])
                        run.bold = True
                        run.font.size = Pt(10)
                        run.font.color.rgb = RGBColor(0xFF, 0xFF, 0xFF)
                    else:
                        if r_idx % 2 == 0:
                            _shade_cell(cell, "F8FAFC")
                        _add_inline(p, row_vals[c_idx], default_color=BODY)
                        for run in p.runs:
                            if run.font.size is None:
                                run.font.size = Pt(10)
            doc.add_paragraph().paragraph_format.space_after = Pt(2)
            continue

        # Headings
        if stripped.startswith("# "):
            h = doc.add_heading(stripped[2:], level=1)
            for run in h.runs:
                run.font.color.rgb = NAVY
            i += 1
            continue
        if stripped.startswith("## "):
            h = doc.add_heading(stripped[3:], level=2)
            for run in h.runs:
                run.font.color.rgb = NAVY
            i += 1
            continue
        if stripped.startswith("### "):
            h = doc.add_heading(stripped[4:], level=3)
            for run in h.runs:
                run.font.color.rgb = BLUE
            i += 1
            continue

        # Bullet list item
        if re.match(r"^[-*]\s+", stripped):
            p = doc.add_paragraph(style="List Bullet")
            p.paragraph_format.space_after = Pt(3)
            _add_inline(p, re.sub(r"^[-*]\s+", "", stripped))
            i += 1
            continue

        # Numbered list item
        if re.match(r"^\d+\.\s+", stripped):
            p = doc.add_paragraph(style="List Number")
            p.paragraph_format.space_after = Pt(3)
            _add_inline(p, re.sub(r"^\d+\.\s+", "", stripped))
            i += 1
            continue

        # Italic caption or subtitle line (*...*)
        if stripped.startswith("*") and stripped.endswith("*") and not stripped.startswith("**") and stripped.count("*") == 2:
            p = doc.add_paragraph()
            p.paragraph_format.space_after = Pt(6)
            _add_inline(p, stripped[1:-1], default_color=SLATE, italic=True)
            i += 1
            continue

        # Regular paragraph (join consecutive prose lines)
        para_lines = [stripped]
        i += 1
        while i < len(lines):
            nxt = lines[i].strip()
            if (
                not nxt
                or nxt.startswith(("#", "```", "|", "![", "- ", "* "))
                or re.match(r"^\d+\.\s+", nxt)
            ):
                break
            para_lines.append(nxt)
            i += 1
        p = doc.add_paragraph()
        p.paragraph_format.space_after = Pt(6)
        _add_inline(p, " ".join(para_lines))

    docx_path.parent.mkdir(parents=True, exist_ok=True)
    doc.save(docx_path)


def export_all_word(blog_root: Path):
    word_dir = blog_root / "word"
    word_dir.mkdir(exist_ok=True)
    for old in word_dir.glob("*.docx"):
        old.unlink()
    for md_path in sorted(blog_root.glob("[0-9][0-9]-*.md")):
        export_markdown_to_docx(md_path, word_dir / md_path.with_suffix(".docx").name, blog_root)
