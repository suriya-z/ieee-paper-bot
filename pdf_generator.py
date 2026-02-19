"""
IEEE-Compliant PDF Generator
Produces a two-column A4 PDF matching IEEE conference paper formatting.

Layout strategy:
  Page 1: Full-width header (title + authors + abstract + index terms)
           followed by two equal body columns.
  Page 2+: Two equal body columns filling the page.

No page numbers are added (IEEE adds them during publication).
"""

import os
import re
import tempfile

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import inch
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_JUSTIFY, TA_RIGHT
from reportlab.platypus import (
    BaseDocTemplate, Frame, PageTemplate, Paragraph,
    Spacer, Table, TableStyle, HRFlowable,
    NextPageTemplate, FrameBreak, CondPageBreak,
)
from reportlab.lib import colors


# ─── IEEE Page Geometry ───────────────────────────────────────────────────────
PAGE_W, PAGE_H = A4          # 595.28 x 841.89 pt
MARGIN_TOP     = 0.75 * inch
MARGIN_BOTTOM  = 1.00 * inch
MARGIN_LEFT    = 0.625 * inch
MARGIN_RIGHT   = 0.625 * inch
COLUMN_GAP     = 0.25 * inch

USABLE_W = PAGE_W - MARGIN_LEFT - MARGIN_RIGHT
COL_W    = (USABLE_W - COLUMN_GAP) / 2


# ─── Styles ───────────────────────────────────────────────────────────────────
def build_styles():
    s = {}

    s["title"] = ParagraphStyle(
        "IEEETitle",
        fontName="Times-Roman",
        fontSize=24,
        leading=28,
        alignment=TA_CENTER,
        spaceBefore=0,
        spaceAfter=8,
    )
    s["author_name"] = ParagraphStyle(
        "IEEEAuthorName",
        fontName="Times-Bold",
        fontSize=10,
        leading=13,
        alignment=TA_CENTER,
        spaceAfter=1,
    )
    s["author_affil"] = ParagraphStyle(
        "IEEEAuthorAffil",
        fontName="Times-Italic",
        fontSize=9,
        leading=11,
        alignment=TA_CENTER,
        spaceAfter=1,
    )
    # Abstract: 9pt italic, full-width
    s["abstract"] = ParagraphStyle(
        "IEEEAbstract",
        fontName="Times-Italic",
        fontSize=9,
        leading=11,
        alignment=TA_JUSTIFY,
        spaceAfter=3,
    )
    # Index Terms: 9pt italic, full-width
    s["index_terms"] = ParagraphStyle(
        "IEEEIndexTerms",
        fontName="Times-Roman",
        fontSize=9,
        leading=11,
        alignment=TA_JUSTIFY,
        spaceAfter=4,
    )
    # Section heading: centered bold 10pt, ALL CAPS roman numeral style
    s["section_heading"] = ParagraphStyle(
        "IEEESectionHeading",
        fontName="Times-Bold",
        fontSize=10,
        leading=13,
        alignment=TA_CENTER,
        spaceBefore=8,
        spaceAfter=3,
    )
    # Body: 10pt justified, first-line indent
    s["body"] = ParagraphStyle(
        "IEEEBody",
        fontName="Times-Roman",
        fontSize=10,
        leading=12,
        alignment=TA_JUSTIFY,
        firstLineIndent=14,
        spaceAfter=0,
    )
    # Body without indent (first paragraph after heading)
    s["body_no_indent"] = ParagraphStyle(
        "IEEEBodyNoIndent",
        fontName="Times-Roman",
        fontSize=10,
        leading=12,
        alignment=TA_JUSTIFY,
        firstLineIndent=0,
        spaceAfter=0,
    )
    # Equation: italic, used for the formula cell in a 3-col equation table
    s["equation"] = ParagraphStyle(
        "IEEEEquation",
        fontName="Times-Italic",
        fontSize=10,
        leading=14,
        alignment=TA_CENTER,
        spaceBefore=0,
        spaceAfter=0,
    )
    # Equation number: right-aligned, same row as formula
    s["eq_number"] = ParagraphStyle(
        "IEEEEquationNumber",
        fontName="Times-Roman",
        fontSize=10,
        leading=14,
        alignment=TA_RIGHT,
        spaceBefore=0,
        spaceAfter=0,
    )
    # Table caption: bold 8pt, centered, ABOVE table — tight spacing
    s["table_caption"] = ParagraphStyle(
        "IEEETableCaption",
        fontName="Times-Bold",
        fontSize=8,
        leading=10,
        alignment=TA_CENTER,
        spaceBefore=3,
        spaceAfter=1,
    )
    # References heading
    s["ref_heading"] = ParagraphStyle(
        "IEEERefHeading",
        fontName="Times-Bold",
        fontSize=10,
        leading=13,
        alignment=TA_CENTER,
        spaceBefore=8,
        spaceAfter=3,
    )
    # Reference entry: 8pt, hanging indent
    s["reference"] = ParagraphStyle(
        "IEEEReference",
        fontName="Times-Roman",
        fontSize=8,
        leading=10,
        alignment=TA_JUSTIFY,
        leftIndent=14,
        firstLineIndent=-14,
        spaceAfter=2,
    )

    return s


# ─── Parse body text → flowables ─────────────────────────────────────────────
def parse_content(text: str, styles: dict, first_no_indent: bool = True) -> list:
    """
    Split text into paragraphs. Detect EQUATION: expr (N) patterns.
    Strip any 'Fig. X' or 'Figure X' references since we have no figures.
    Normalise common textual artifacts: 'percent' -> '%', etc.
    """
    # Remove figure references
    text = re.sub(
        r'\b(as shown in |see |refer to |illustrated in |depicted in )?'
        r'(Fig\.|Figure)\s*\d+[a-z]?(\s*\([^)]*\))?[,.]?',
        '', text, flags=re.IGNORECASE
    )
    text = re.sub(r'\s{2,}', ' ', text)  # collapse double spaces

    # Fix common word artifacts from AI output
    text = re.sub(r'\bpercent\b', '%', text, flags=re.IGNORECASE)
    text = re.sub(r'(\d)\s*%', r'\1%', text)   # "95.3 %" -> "95.3%"
    # IEEE inline table refs: "TABLE I" in body text -> "Table I" (only caption is ALL CAPS)
    text = re.sub(r'\bTABLE\s+(I{1,3}|IV|V?I{0,3}|IX|XI{0,3})\b', lambda m: 'Table ' + m.group(1), text)
    # Grammar: missing possessives the AI commonly omits
    text = re.sub(r"\bmodels\s+(ability|performance|capacity|accuracy|capability)",
                  r"model's \1", text, flags=re.IGNORECASE)
    text = re.sub(r"\bsystems\s+(ability|performance|capacity|accuracy|capability)",
                  r"system's \1", text, flags=re.IGNORECASE)
    text = re.sub(r"\bcandidates\s+(qualifications|experience|skills|answers|responses|knowledge)",
                  r"candidate's \1", text, flags=re.IGNORECASE)
    text = re.sub(r"\binterviewers\s+(judgment|assessment|evaluation|feedback)",
                  r"interviewer's \1", text, flags=re.IGNORECASE)
    # Hyphen consistency: "real time" -> "real-time"
    text = re.sub(r'\breal\s+time\b', 'real-time', text, flags=re.IGNORECASE)

    flowables = []
    paragraphs = re.split(r'\n\n+', text) if '\n\n' in text else text.split('\n')
    paragraphs = [p.strip() for p in paragraphs if p.strip()]

    eq_pat = re.compile(r'EQUATION:\s*(.+?)\s*\((\d+)\)', re.IGNORECASE)
    is_first = True

    for para in paragraphs:
        m = eq_pat.search(para)
        if m:
            before = para[:m.start()].strip()
            if before:
                st = styles["body_no_indent"] if (is_first and first_no_indent) else styles["body"]
                flowables.append(Paragraph(before, st))
                is_first = False

            # IEEE equation: formula centered, number pinned to right margin — same line
            eq_expr   = m.group(1).strip()
            eq_number = f"({m.group(2)})"
            # 2-col table: formula (85% of col) | eq-number (15%, right-aligned)
            eq_row = [[
                Paragraph(f"<i>{eq_expr}</i>", styles["equation"]),
                Paragraph(eq_number, styles["eq_number"]),
            ]]
            eq_table = Table(eq_row, colWidths=[COL_W * 0.85, COL_W * 0.15])
            eq_table.setStyle(TableStyle([
                ("ALIGN",         (0, 0), (0, 0), "CENTER"),
                ("ALIGN",         (1, 0), (1, 0), "RIGHT"),
                ("VALIGN",        (0, 0), (-1, -1), "MIDDLE"),
                ("TOPPADDING",    (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                ("LEFTPADDING",   (0, 0), (0, 0), 0),
                ("RIGHTPADDING",  (0, 0), (0, 0), 0),
                ("LEFTPADDING",   (1, 0), (1, 0), 4),
                ("RIGHTPADDING",  (1, 0), (1, 0), 0),
            ]))
            flowables.append(eq_table)

            after = para[m.end():].strip()
            if after:
                flowables.append(Paragraph(after, styles["body"]))
                is_first = False
        else:
            para = para.replace('\n', ' ')
            st = styles["body_no_indent"] if (is_first and first_no_indent) else styles["body"]
            flowables.append(Paragraph(para, st))
            is_first = False

    return flowables


# ─── IEEE Table ───────────────────────────────────────────────────────────────
def build_ieee_table(table_data: dict, styles: dict) -> list:
    """
    Caption ABOVE table, two-line format:
        TABLE I
        PERFORMANCE COMPARISON OF METHODS
    Horizontal rules only, 8pt font, no background color.
    """
    flowables = []
    raw_caption = table_data.get("caption", "TABLE I: Results")
    headers = table_data.get("headers", [])
    rows    = table_data.get("rows", [])

    # Parse "TABLE I: Performance Comparison" → label + subtitle
    if ":" in raw_caption:
        label, subtitle = raw_caption.split(":", 1)
    else:
        label, subtitle = raw_caption, ""
    label    = label.strip().upper()
    subtitle = subtitle.strip().upper()

    caption_html = f"<b>{label}</b>"
    if subtitle:
        caption_html += f"<br/>{subtitle}"

    flowables.append(Paragraph(caption_html, styles["table_caption"]))

    if not headers:
        return flowables

    col_count = len(headers)
    col_width = (COL_W - 2) / col_count

    tbl = Table([headers] + rows, colWidths=[col_width] * col_count, repeatRows=1)
    tbl.setStyle(TableStyle([
        ("FONTNAME",      (0, 0), (-1,  0), "Times-Bold"),
        ("FONTSIZE",      (0, 0), (-1, -1), 8),
        ("FONTNAME",      (0, 1), (-1, -1), "Times-Roman"),
        ("ALIGN",         (0, 0), (-1, -1), "CENTER"),
        ("VALIGN",        (0, 0), (-1, -1), "MIDDLE"),
        ("LINEABOVE",     (0, 0), (-1,  0), 1.0, colors.black),
        ("LINEBELOW",     (0, 0), (-1,  0), 0.5, colors.black),
        ("LINEBELOW",     (0,-1), (-1, -1), 1.0, colors.black),
        ("TOPPADDING",    (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("LEFTPADDING",   (0, 0), (-1, -1), 8),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 8),
    ]))
    flowables.append(tbl)
    flowables.append(Spacer(1, 4))
    return flowables


# ─── Page Templates ───────────────────────────────────────────────────────────
def _no_op(canvas, doc):
    """No page decorations — IEEE adds page numbers during publication."""
    pass


def make_page_templates(header_h: float):
    """
    FirstPage: one full-width header frame at top + two body column frames below.
    TwoCol:    two full-height body column frames.
    """
    body_h_p1 = PAGE_H - MARGIN_TOP - header_h - MARGIN_BOTTOM - 4

    # ── First page ──
    hdr = Frame(
        MARGIN_LEFT,
        PAGE_H - MARGIN_TOP - header_h,
        USABLE_W, header_h,
        leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0,
        id="hdr", showBoundary=0,
    )
    p1L = Frame(
        MARGIN_LEFT, MARGIN_BOTTOM,
        COL_W, body_h_p1,
        leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0,
        id="p1L", showBoundary=0,
    )
    p1R = Frame(
        MARGIN_LEFT + COL_W + COLUMN_GAP, MARGIN_BOTTOM,
        COL_W, body_h_p1,
        leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0,
        id="p1R", showBoundary=0,
    )
    first_page = PageTemplate(
        id="FirstPage",
        frames=[hdr, p1L, p1R],
        pagesize=A4,
        onPage=_no_op,
    )

    # ── Subsequent pages ──
    body_h = PAGE_H - MARGIN_TOP - MARGIN_BOTTOM
    L = Frame(
        MARGIN_LEFT, MARGIN_BOTTOM,
        COL_W, body_h,
        leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0,
        id="L", showBoundary=0,
    )
    R = Frame(
        MARGIN_LEFT + COL_W + COLUMN_GAP, MARGIN_BOTTOM,
        COL_W, body_h,
        leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0,
        id="R", showBoundary=0,
    )
    two_col = PageTemplate(
        id="TwoCol",
        frames=[L, R],
        pagesize=A4,
        onPage=_no_op,
    )

    return [first_page, two_col]


# ─── Main Generator ───────────────────────────────────────────────────────────
def generate_ieee_pdf(paper_data: dict, output_path: str = None) -> str:
    """
    Generate an IEEE-formatted two-column PDF.
    Returns the path to the generated PDF file.
    """
    if output_path is None:
        tmp = tempfile.NamedTemporaryFile(suffix=".pdf", delete=False)
        output_path = tmp.name
        tmp.close()

    styles     = build_styles()
    title_text = paper_data.get("title", "Untitled Paper")
    authors    = paper_data.get("authors", [])

    # ── Estimate header height ────────────────────────────────────────────────
    # Header now contains ONLY: title + authors + one HR rule
    # Abstract and Index Terms go into the two-column body.
    n_authors = max(len(authors), 1)
    header_h  = 40 + n_authors * 65 + 12   # title + authors + spacers/rule
    header_h  = max(100, min(header_h, int(PAGE_H * 0.35)))

    # ── Apply IEEE title case to the paper title ─────────────────────────────
    # Lowercase exceptions (prepositions, articles, conjunctions)
    _LC = {'a','an','the','and','but','or','for','nor','on','at','to','by',
           'in','of','up','as','if','vs','via','per'}
    def _title_case(s: str) -> str:
        words = s.split()
        result = []
        for i, w in enumerate(words):
            # Always capitalise first and last word; keep all-caps acronyms intact
            if i == 0 or i == len(words) - 1 or w.isupper():
                result.append(w[0].upper() + w[1:] if not w.isupper() else w)
            elif w.lower() in _LC:
                result.append(w.lower())
            else:
                result.append(w[0].upper() + w[1:] if w else w)
        return ' '.join(result)
    title_text = _title_case(title_text)

    # ── Build story ───────────────────────────────────────────────────────────
    story = [NextPageTemplate("FirstPage")]

    # Title
    story.append(Paragraph(title_text, styles["title"]))
    story.append(Spacer(1, 6))

    # Authors — side by side in a table if multiple
    if authors:
        cells = []
        for a in authors:
            name  = a.get("name", "")
            dept  = a.get("department", "")
            uni   = a.get("university", "")
            city  = a.get("city", "")
            email = a.get("email", "")
            col = [
                Paragraph(f"<b>{name}</b>", styles["author_name"]),
                Paragraph(dept,  styles["author_affil"]),
                Paragraph(uni,   styles["author_affil"]),
                Paragraph(city,  styles["author_affil"]),
                Paragraph(f"<i>{email}</i>", styles["author_affil"]),
            ]
            cells.append(col)

        if len(cells) == 1:
            for item in cells[0]:
                story.append(item)
        else:
            cw = USABLE_W / len(cells)
            max_r = max(len(c) for c in cells)
            rows = []
            for r in range(max_r):
                rows.append([c[r] if r < len(c) else Spacer(1, 1) for c in cells])
            at = Table(rows, colWidths=[cw] * len(cells))
            at.setStyle(TableStyle([
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("ALIGN",  (0, 0), (-1, -1), "CENTER"),
                ("TOPPADDING",    (0, 0), (-1, -1), 1),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 1),
            ]))
            story.append(at)

    story.append(Spacer(1, 6))
    story.append(HRFlowable(width=USABLE_W, thickness=0.5, color=colors.black))
    story.append(Spacer(1, 3))

    # FrameBreak: exit the full-width header frame → enter left body column
    story.append(FrameBreak())

    # Switch subsequent pages to TwoCol template
    story.append(NextPageTemplate("TwoCol"))

    # ── Abstract (in two-column body, spans left column first) ────────────────
    abstract = paper_data.get("abstract", "")
    if abstract:
        story.append(Paragraph(
            f"<b><i>Abstract</i></b><i>\u2014{abstract}</i>",
            styles["abstract"]
        ))
        story.append(Spacer(1, 3))

    # ── Index Terms (in two-column body) ──────────────────────────────────────
    keywords = paper_data.get("keywords", [])
    if keywords:
        kw_str = ", ".join(keywords)
        story.append(Paragraph(
            f"<b><i>Index Terms</i></b><i>\u2014{kw_str}</i>",
            styles["index_terms"]
        ))
        story.append(Spacer(1, 6))

    # ── Body sections ─────────────────────────────────────────────────────────
    sections_order = [
        "introduction",
        "related_work",
        "methodology",
        "implementation",
        "results",
        "conclusion",
    ]
    table_inserted = False

    for key in sections_order:
        sec = paper_data.get(key)
        if not sec:
            continue
        heading = sec.get("title", key.replace("_", " ").upper()).upper()
        content = sec.get("content", "")

        story.append(Paragraph(heading, styles["section_heading"]))
        story.extend(parse_content(content, styles, first_no_indent=True))
        story.append(Spacer(1, 3))

        # Table goes after results section
        if key == "results" and not table_inserted:
            td = paper_data.get("table")
            if td:
                story.extend(build_ieee_table(td, styles))
                table_inserted = True

    # ── References ────────────────────────────────────────────────────────────
    refs = paper_data.get("references", [])
    if refs:
        story.append(Paragraph("REFERENCES", styles["ref_heading"]))
        for ref in refs:
            ref = ref.strip().replace("&", "&amp;")
            # IEEE uses double quotes — normalise any single-quoted titles
            ref = re.sub(r"'([^']+)'", r'"\1"', ref)
            story.append(Paragraph(ref, styles["reference"]))

    # ── Build document ────────────────────────────────────────────────────────
    doc = BaseDocTemplate(
        output_path,
        pagesize=A4,
        leftMargin=MARGIN_LEFT,
        rightMargin=MARGIN_RIGHT,
        topMargin=MARGIN_TOP,
        bottomMargin=MARGIN_BOTTOM,
        title=title_text,
        author=authors[0].get("name", "Author") if authors else "Author",
        subject="IEEE Conference Paper",
        creator="IEEE Paper Generator Bot",
        # PDF/A and accessibility tags for IEEE Xplore compliance
        keywords="IEEE, conference, paper",
    )
    doc.addPageTemplates(make_page_templates(header_h))
    doc.build(story)
    return output_path
