"""Render crisp, modern SVG-to-PNG technical architecture diagrams."""

import html
from pathlib import Path
import cairosvg


def _esc(text):
    return html.escape(str(text), quote=True)


def _svg_wrap(width, height, body, title=""):
    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">
  <defs>
    <linearGradient id="bgGrad" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0%" stop-color="#f8fafc"/>
      <stop offset="100%" stop-color="#eef4fb"/>
    </linearGradient>
    <linearGradient id="navyGrad" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0%" stop-color="#0f2942"/>
      <stop offset="100%" stop-color="#1a4369"/>
    </linearGradient>
    <linearGradient id="azureGrad" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0%" stop-color="#005ba1"/>
      <stop offset="100%" stop-color="#0078d4"/>
    </linearGradient>
    <linearGradient id="tealGrad" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0%" stop-color="#0f766e"/>
      <stop offset="100%" stop-color="#0d9488"/>
    </linearGradient>
    <linearGradient id="amberGrad" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0%" stop-color="#b45309"/>
      <stop offset="100%" stop-color="#d97706"/>
    </linearGradient>
    <linearGradient id="purpleGrad" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0%" stop-color="#5b21b6"/>
      <stop offset="100%" stop-color="#7c3aed"/>
    </linearGradient>
    <filter id="cardShadow" x="-4%" y="-4%" width="108%" height="112%">
      <feDropShadow dx="0" dy="4" stdDeviation="6" flood-color="#0f172a" flood-opacity="0.08"/>
    </filter>
    <marker id="arrowBlue" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
      <path d="M 0 1 L 10 5 L 0 9 z" fill="#0078d4"/>
    </marker>
    <marker id="arrowAmber" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
      <path d="M 0 1 L 10 5 L 0 9 z" fill="#d97706"/>
    </marker>
    <marker id="arrowTeal" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
      <path d="M 0 1 L 10 5 L 0 9 z" fill="#0d9488"/>
    </marker>
    <marker id="arrowSlate" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
      <path d="M 0 1 L 10 5 L 0 9 z" fill="#64748b"/>
    </marker>
    <marker id="arrowRed" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
      <path d="M 0 1 L 10 5 L 0 9 z" fill="#dc2626"/>
    </marker>
  </defs>
  <rect width="{width}" height="{height}" fill="url(#bgGrad)"/>
  <g font-family="DejaVu Sans, Arial, sans-serif">
    {body}
  </g>
</svg>"""


def _header(title, subtitle, width=1400):
    return f"""
  <rect x="0" y="0" width="{width}" height="6" fill="#0078d4"/>
  <text x="48" y="50" font-size="28" font-weight="bold" fill="#0f2942">{_esc(title)}</text>
  <text x="48" y="78" font-size="15" fill="#475569">{_esc(subtitle)}</text>
"""


def _card(x, y, w, h, title, lines, *, accent="#0078d4", fill="#ffffff", badge=None, badge_bg="#e0f2fe", badge_fg="#0369a1"):
    parts = [
        f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="12" fill="{fill}" stroke="#cbd5e1" stroke-width="1.5" filter="url(#cardShadow)"/>',
        f'<rect x="{x}" y="{y}" width="{w}" height="8" rx="4" fill="{accent}"/>',
    ]
    title_y = y + 34
    body_y = y + 60
    if badge:
        bw = max(76, len(badge) * 7 + 18)
        parts.append(f'<rect x="{x + 16}" y="{y + 16}" width="{bw}" height="20" rx="10" fill="{badge_bg}"/>')
        parts.append(f'<text x="{x + 16 + bw / 2}" y="{y + 30}" font-size="10" font-weight="bold" text-anchor="middle" fill="{badge_fg}">{_esc(badge)}</text>')
        title_y = y + 54
        body_y = y + 78
    parts.append(f'<text x="{x + 16}" y="{title_y}" font-size="15" font-weight="bold" fill="#0f172a">{_esc(title)}</text>')
    for idx, line in enumerate(lines):
        ly = body_y + idx * 21
        parts.append(f'<text x="{x + 16}" y="{ly}" font-size="12.5" fill="#334155">{_esc(line)}</text>')
    return "\n".join(parts)


def _pill(x, y, w, h, text, bg="#0f2942", fg="#ffffff", size=12):
    return (
        f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{h // 2}" fill="{bg}"/>'
        f'<text x="{x + w / 2}" y="{y + h / 2 + 4}" font-size="{size}" font-weight="bold" text-anchor="middle" fill="{fg}">{_esc(text)}</text>'
    )


def render_svg_to_png(svg_text, out_path: Path, scale=1.5):
    cairosvg.svg2png(bytestring=svg_text.encode("utf-8"), write_to=str(out_path), scale=scale)


def build_all_diagrams(media_dir: Path):
    # 1. 28-skill-layers.png: 4-Layer Agent Skill Architecture
    body = _header(
        "Four-Layer Agent Skill Architecture",
        "Separating conversational policy (SKILL.md), deterministic validation (Python CLI), graph orchestration (Agent Framework), and model inference (Azure OpenAI)",
    )
    layers = [
        (110, "LAYER 1 · TEACHER / OPERATOR INTENT", "Copilot CLI or Skill Host",
         ["Natural-language goal (e.g., inspect state, grade, review, export)",
          "Never sent verbatim as an Azure handwriting prompt"],
         "#5b21b6", "CONVERSATIONAL", "#ede9fe", "#5b21b6"),
        (235, "LAYER 2 · AGENT SKILL POLICY (.github/skills/handwriting-grading/)", "SKILL.md + Progressive-Disclosure references/*.md",
         ["Inspects workspace artifacts (manifest, approval.json) to orient state",
          "Enforces stop rules (check-scans), cost-preview consent, and HIL prompts"],
         "#0078d4", "INSTRUCTIONS ONLY", "#e0f2fe", "#0369a1"),
        (360, "LAYER 3 · DETERMINISTIC PYTHON CLI & VALIDATION", "src/handwriting_grader/ (cli.py, preflight, pricing.py, grade_review.py)",
         ["Enforces SHA-256 approval bindings, --confirm-cost / --confirm-reviewed / --confirm-send",
          "Runs pypdfium2 rendering, FFT alignment, blank filtering, and [0, max_marks] bounds"],
         "#0f766e", "SECURITY BOUNDARY", "#ccfbf1", "#0f766e"),
        (485, "LAYER 4 · MICROSOFT AGENT FRAMEWORK & AZURE OPENAI", "WorkflowBuilder (3 Executors) -> Azure Responses & Images API",
         ["Executes ValidateApproval -> ExecuteGrading (sync threads) -> RequireHumanReview",
          "Proposes structured JSON drafts (store=False); never grants human approval"],
         "#b45309", "PROPOSAL ENGINE", "#fef3c7", "#b45309"),
    ]
    for idx, (y, label, title, lines, accent, badge, bbg, bfg) in enumerate(layers):
        body += f'<text x="48" y="{y - 8}" font-size="11" font-weight="bold" fill="{accent}">{_esc(label)}</text>'
        body += _card(48, y, 1304, 96, title, lines, accent=accent, badge=badge, badge_bg=bbg, badge_fg=bfg)
        if idx < len(layers) - 1:
            body += f'<line x1="700" y1="{y + 98}" x2="700" y2="{y + 122}" stroke="#64748b" stroke-width="2.5" marker-end="url(#arrowSlate)"/>'
    render_svg_to_png(_svg_wrap(1400, 610, body), media_dir / "28-skill-layers.png")

    # 2. 11-architecture.png: 6-Gate Cryptographic HIL State Machine & Pipeline
    body = _header(
        "Six-Gate Cryptographic HIL State Machine & Pipeline",
        "Every stage binds upstream inputs via SHA-256 approval.json; downstream tools abort on any hash mismatch",
    )
    cards = [
        (48, 115, 410, 145, "1. Preflight & Scan Consensus",
         ["preflight: path jail + roster + P = S × N",
          "check-scans: 4x FFT consensus (offline)",
          "prepare-attendance -> approve-attendance"], "#0078d4", "GATE 1 · SHA-256"),
        (495, 115, 410, 145, "2. Rubric & Fact Verification",
         ["import-rubric (XLSX) or extract-rubric (DOCX)",
          "Optional verify-rubric (web_search, uncached)",
          "approve-rubric --confirm-reviewed"], "#0078d4", "GATE 2 · SHA-256"),
        (942, 115, 410, 145, "3. Regions & Browser Editor",
         ["prepare-regions: pypdfium2 200 DPI",
          "Optional suggest-regions (0..1000 boxes)",
          "review-regions (127.0.0.1 #TOKEN) -> approval"], "#0078d4", "GATE 3 · SHA-256"),
        (942, 315, 410, 155, "4. Resumable Grading Engine",
         ["grade --confirm-cost (Agent Framework)",
          "Phase A: Metadata OCR (35 scripts/req)",
          "Phase B: Blank filter + Batch/Item grading"], "#b45309", "--confirm-cost"),
        (495, 315, 410, 155, "5. Blind HIL Review & Diagnostics",
         ["review-grading: blind marksheet + snapshots",
          "cluster-answers: lexical or --confirm-cost embed",
          "check-grading-review -> approve-grading"], "#0f766e", "GATE 4 · SHA-256"),
        (48, 315, 410, 155, "6. Reports, AI Analysis & Delivery",
         ["report + analytics (offline, 0 AI cost)",
          "ai-analysis -> approve-analysis -> advanced-report",
          "moodle-export | preview->approve->send-email"], "#5b21b6", "GATES 5 & 6"),
    ]
    for x, y, w, h, title, lines, accent, badge in cards:
        body += _card(x, y, w, h, title, lines, accent=accent, badge=badge)
    # Connectors
    body += '<line x1="460" y1="188" x2="490" y2="188" stroke="#0078d4" stroke-width="2.5" marker-end="url(#arrowBlue)"/>'
    body += '<line x1="907" y1="188" x2="937" y2="188" stroke="#0078d4" stroke-width="2.5" marker-end="url(#arrowBlue)"/>'
    body += '<line x1="1147" y1="262" x2="1147" y2="310" stroke="#d97706" stroke-width="2.5" marker-end="url(#arrowAmber)"/>'
    body += '<line x1="940" y1="392" x2="910" y2="392" stroke="#0d9488" stroke-width="2.5" marker-end="url(#arrowTeal)"/>'
    body += '<line x1="493" y1="392" x2="463" y2="392" stroke="#0d9488" stroke-width="2.5" marker-end="url(#arrowTeal)"/>'
    # Recovery & Regrade bar
    body += _card(
        48, 505, 1304, 112,
        "Isolated Recovery & Child Regrading (Never Mutates Parent History)",
        ["Interrupted run: resume-grading (atomic_json + processing.lock)  ·  Failed items: retry-grading (--align-images / --re-ocr-id / --question Q)",
         "Changed rubric or crop: regrade --run CHILD_RUN (reruns 1 question for all present students; clears all reviewed flags for fresh HIL approval)"],
        accent="#dc2626", fill="#fff8f8", badge="ISOLATED CHILD", badge_bg="#fee2e2", badge_fg="#b91c1c",
    )
    render_svg_to_png(_svg_wrap(1400, 640, body), media_dir / "11-architecture.png")

    # 3. 29-region-pipeline.png: Region Extraction, Localhost Review & FFT Alignment
    body = _header(
        "Region Extraction, Localhost Review & 4-Quadrant FFT Alignment",
        "Pure-Python 200 DPI rendering, rubric-bound 0-1000 proposals, token-hardened browser editing, and outlier-rejected rigid alignment",
    )
    steps = [
        (48, 115, 240, 190, "1. prepare-regions",
         ["pypdfium2 @ 200 DPI", "scale = 200 / 72.0", "Script 1 -> images/{p}.jpg", "Records exact (W, H)", "SHA-256 in manifest.json"], "#0078d4", "OFFLINE"),
        (312, 115, 250, 190, "2. suggest-regions",
         ["Requires approved rubric", "Injects exact question_ids", "0..1000 normalized boxes", "Edge-consistent rounding", "Writes ai_suggestions.json"], "#b45309", "OPTIONAL AI"),
        (586, 115, 255, 190, "3. review-regions",
         ["127.0.0.1 HTTP server", "URL #TOKEN + Origin check", "Live missing-box banner", "Draw / drag / resize / nudge", "-> annotations + approval"], "#0f766e", "HIL BROWSER"),
        (865, 115, 255, 190, "4. alignment.py",
         ["2x downsample, ink >= 35", "4-quadrant Hanning FFT", "Cross-power phase corr.", ">=3 quads <= 15px residual", "Else returns (0, 0, 0)"], "#0078d4", "AUTO ON GRADE"),
        (1144, 115, 208, 190, "5. Filter & Crop",
         ["local_filter.py (Pillow)", "Inset dark-pixel ratio", "Blank -> 0 locally ($0)", "crop_image() enhance(3)", "In-memory PNG bytes"], "#5b21b6", "PRE-INFERENCE"),
    ]
    for idx, (x, y, w, h, title, lines, accent, badge) in enumerate(steps):
        body += _card(x, y, w, h, title, lines, accent=accent, badge=badge)
        if idx < len(steps) - 1:
            nx = steps[idx + 1][0]
            body += f'<line x1="{x + w + 2}" y1="210" x2="{nx - 4}" y2="210" stroke="#0078d4" stroke-width="2.5" marker-end="url(#arrowBlue)"/>'
    body += _card(
        48, 335, 1304, 112,
        "Pre-Region Safety Guard: check-scans (Runs Before prepare-regions AND Before grade)",
        ["4x downsampled FFT phase correlation compares every script against cohort majority consensus (catches Script 1 itself if 180°/90°/270°/swapped).",
         "Zero AI cost. Never silently flips or reorders PDFs—reports exact 1-based PDF page numbers so the operator fixes the physical scan."],
        accent="#dc2626", fill="#fff8f8", badge="STOP RULE", badge_bg="#fee2e2", badge_fg="#b91c1c",
    )
    render_svg_to_png(_svg_wrap(1400, 470, body), media_dir / "29-region-pipeline.png")

    # 4. 30-model-routing.png: Multi-Role Azure OpenAI Routing & Batch/Item Execution
    body = _header(
        "Multi-Role Azure OpenAI Routing & Execution Modes",
        "Dedicated deployment aliases per task family, synchronous multi-image batching, strict JSON schemas, and Python range enforcement",
    )
    roles = [
        (48, 115, 310, 155, "Vision & Spatial Roles",
         ["annotation -> gpt-6.1-terra", "grading / batch_grading -> terra", "Crop boxes, diagrams, handwriting"], "#0078d4", "VISION"),
        (380, 115, 310, 155, "Text & Extraction Roles",
         ["marking_scheme -> gpt-6-luna", "ocr / metadata -> gpt-6-luna", "student_feedback -> gpt-6-luna"], "#0f766e", "FAST TEXT"),
        (712, 115, 310, 155, "Reasoning & Analytics",
         ["moderation -> gpt-6.2-sol", "analytics -> gpt-6.2-sol", "Hard rubrics -> gpt-6.2-astra"], "#5b21b6", "REASONING"),
        (1044, 115, 308, 155, "Isolated Aux Deployments",
         ["embedding -> text-embedding", "analytics_image -> image model", "Separate --image-model-config"], "#b45309", "EXEMPT FLOOR"),
    ]
    for x, y, w, h, title, lines, accent, badge in roles:
        body += _card(x, y, w, h, title, lines, accent=accent, badge=badge)
    body += _card(
        48, 300, 635, 175,
        "Phase A: Roster-Constrained Metadata OCR",
        ["Sends ID, CLASS, NAME crops (up to 35 scripts = 105 images/request)",
         "Injects Official Enrolled Roster JSON to resolve cursive/smudged IDs",
         "Falls back to per-field OCR on error; never authenticates identity"],
        accent="#0f766e", badge="35 SCRIPTS / REQ",
    )
    body += _card(
        717, 300, 635, 175,
        "Phase B: --mode batch (Default) vs. --mode item",
        ["--mode batch: sync multi-image (<=50 scripts/question), NOT Azure Async Batch",
         "Within-group comparison + moderator_flag + moderator_note in 1 pass",
         "--mode item: per-crop GradeResponse + text-only ModerationResponse"],
        accent="#0078d4", badge="<=50 SCRIPTS / REQ",
    )
    body += _card(
        48, 500, 1304, 112,
        "Transport & Adversarial Safety Boundary (azure_ai.py + grading.py)",
        ["Responses API with store=False, strict_schema() (additionalProperties: false), and explicit HTTPS Azure endpoint (no public OpenAI fallback).",
         "Prompts treat handwriting as untrusted data; Python enforces 0 <= mark <= max_marks and exact script_index set equality."],
        accent="#0f2942", badge="PYTHON ENFORCED",
    )
    render_svg_to_png(_svg_wrap(1400, 635, body), media_dir / "30-model-routing.png")

    # 5. 16-framework.png: Microsoft Agent Framework & Supply-Chain Boundary
    body = _header(
        "Microsoft Agent Framework Orchestration & Threading Boundary",
        "Pinned minimal packages (agent-framework-core==1.26.0, agent-framework-openai==1.18.2), typed Executors, and human review outside the graph",
    )
    body += _card(
        48, 115, 290, 175,
        "0. CLI & Consent Gate",
        ["grade (default) or", "workflow-grade", "Requires --confirm-cost", "Passes typed 'grade'", "control message"],
        accent="#5b21b6", badge="CLI ENTRY",
    )
    body += '<rect x="366" y="96" width="668" height="214" rx="14" fill="#eff6ff" stroke="#93c5fd" stroke-width="2" stroke-dasharray="6,4"/>'
    body += '<text x="384" y="118" font-size="12" font-weight="bold" fill="#1d4ed8">MICROSOFT AGENT FRAMEWORK · WorkflowBuilder (max_iterations=4)</text>'
    execs = [
        (384, 134, 195, 156, "1. ValidateApproval",
         ["approved_inputs()", "Checks attendance,", "rubric, regions,", "and label parity"], "#0078d4", "EXECUTOR 1"),
        (602, 134, 195, 156, "2. ExecuteGrading",
         ["asyncio.to_thread()", "Runs sync grade_exam", "Question threads stay", "inside sync engine"], "#b45309", "EXECUTOR 2"),
        (820, 134, 195, 156, "3. HumanReview",
         ["RequireHumanReview", "WorkflowContext[Never]", "yield_output(path)", "No auto-approval"], "#0f766e", "EXECUTOR 3"),
    ]
    for idx, (x, y, w, h, title, lines, accent, badge) in enumerate(execs):
        body += _card(x, y, w, h, title, lines, accent=accent, badge=badge)
        if idx < 2:
            body += f'<line x1="{x + w + 2}" y1="212" x2="{execs[idx + 1][0] - 4}" y2="212" stroke="#0078d4" stroke-width="2.5" marker-end="url(#arrowBlue)"/>'
    body += '<line x1="340" y1="212" x2="380" y2="212" stroke="#5b21b6" stroke-width="2.5" marker-end="url(#arrowBlue)"/>'
    body += _card(
        1062, 115, 290, 175,
        "4. Outside Workflow HIL",
        ["review-grading UI", "check-grading-review", "approve-grading", "--confirm-reviewed", "-> grading/approval.json"],
        accent="#0f766e", badge="TEACHER HIL",
    )
    body += '<line x1="1017" y1="212" x2="1058" y2="212" stroke="#0d9488" stroke-width="2.5" stroke-dasharray="5,4" marker-end="url(#arrowTeal)"/>'
    body += _card(
        48, 332, 1304, 112,
        "Engineering & Supply-Chain Invariants",
        ["Supply-chain pin: avoids umbrella agent-framework 1.26.1/1.26.2 (GHSA-764m-3ppc-5m73) and unrelated provider extras.",
         "--orchestrator python invokes the exact same grade_function; Framework clients are never shared across OS threads."],
        accent="#dc2626", fill="#fff8f8", badge="SECURITY PIN", badge_bg="#fee2e2", badge_fg="#b91c1c",
    )
    render_svg_to_png(_svg_wrap(1400, 468, body), media_dir / "16-framework.png")

    # 6. 17-pricing-gate.png: Fail-Closed Cost Governance & Token Accounting
    body = _header(
        "Fail-Closed Cost Governance & Token Accounting",
        "Zero guessed prices: live Retail Prices API lookup, first-use run latch, 272k context tiers, and honest UNPRICED/null reporting",
    )
    p_steps = [
        (48, 115, 240, 175, "1. discover-models",
         ["Offline template only", "No inference or quota", "Refuses overwrite", "Curated GA families"], "#475569", "OFFLINE"),
        (312, 115, 250, 175, "2. fetch-pricing",
         ["Public Retail Prices API", "Global / Data Zone Std", "Exact meter & SKU match", "Writes pricing_sources"], "#0078d4", "NO CREDENTIALS"),
        (586, 115, 250, 175, "3. Preview & Consent",
         ["Shows target, payload,", "and request estimate", "Requires explicit", "--confirm-cost flag"], "#b45309", "CONSENT GATE"),
        (860, 115, 250, 175, "4. RunPricingVerifier",
         ["Checks config SHA-256", "Refreshes live rates once", "Latches _blocked_reason", "on missing/changed rate"], "#dc2626", "RUNTIME LATCH"),
        (1134, 115, 218, 175, "5. azure_usage.jsonl",
         ["P - C - W ordinary input", "272k short/long tiers", "30m/12h cache_write", "Missing -> UNPRICED"], "#0f766e", "TELEMETRY"),
    ]
    for idx, (x, y, w, h, title, lines, accent, badge) in enumerate(p_steps):
        body += _card(x, y, w, h, title, lines, accent=accent, badge=badge)
        if idx < len(p_steps) - 1:
            nx = p_steps[idx + 1][0]
            body += f'<line x1="{x + w + 2}" y1="202" x2="{nx - 4}" y2="202" stroke="#0078d4" stroke-width="2.5" marker-end="url(#arrowBlue)"/>'
    render_svg_to_png(_svg_wrap(1400, 320, body), media_dir / "17-pricing-gate.png")

    # 7. 31-hil-delivery.png: Post-Approval Outputs, LMS Export, Email & Slim Cleanup
    body = _header(
        "Post-Approval Outputs: Analytics, LMS Export, Email & Cleanup",
        "All downstream artifacts verify grading/approval.json; distribution and cleanup enforce separate preview and confirmation flags",
    )
    d_cards = [
        (48, 115, 310, 175, "report & analytics (Offline)",
         ["score_report + details_score_report", "<ID>_<NAME>_script-*.pdf", "statistics.xlsx + boxplots PNGs", "0 AI cost; blank pass if unset"], "#0078d4", "OFFLINE"),
        (380, 115, 310, 175, "ai-analysis -> advanced-report",
         ["ai-analysis (--confirm-cost)", "approve-analysis (--confirm-reviewed)", "teacher-report.docx + class.pptx", "Opt-in --image-model-config"], "#5b21b6", "GATE 5 · SHA-256"),
        (712, 115, 310, 175, "moodle-export (Offline LMS)",
         ["student_pdfs/<ID>_<Name>.pdf", "Feedback cover + marked script", "recipients.csv from Moodle CSV", "Worksheet CSV + feedback_files.zip"], "#0f766e", "LMS READY"),
        (1044, 115, 308, 175, "Email & Slim Cleanup",
         ["preview-email -> approve-email", "send-email --confirm-send (STARTTLS)", "delivery.json skips sent/ambiguous", "clean --confirm-delete -> slim .zip"], "#b45309", "GATE 6 · STARTTLS"),
    ]
    for x, y, w, h, title, lines, accent, badge in d_cards:
        body += _card(x, y, w, h, title, lines, accent=accent, badge=badge)
    render_svg_to_png(_svg_wrap(1400, 320, body), media_dir / "31-hil-delivery.png")
