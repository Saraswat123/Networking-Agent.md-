"""
Convert markdown CV to PDF using reportlab.
Usage: python3 md_to_pdf.py input.md output.pdf
Fixes: clickable links in contact line, word-wrap in tables, publications section.
"""
import re, sys
from pathlib import Path
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, HRFlowable, Table, TableStyle
from reportlab.lib.enums import TA_CENTER, TA_LEFT


DARK   = colors.HexColor('#1a1a2e')
ACCENT = colors.HexColor('#2563eb')
GREY   = colors.HexColor('#555555')
LGREY  = colors.HexColor('#f0f2f5')
TGREY  = colors.HexColor('#333333')

def _styles():
    return {
        'name':    ParagraphStyle('name',    fontSize=20, leading=24, textColor=DARK, alignment=TA_CENTER, fontName='Helvetica-Bold'),
        'title':   ParagraphStyle('title',   fontSize=11, leading=14, textColor=ACCENT, alignment=TA_CENTER, fontName='Helvetica-Bold'),
        'contact': ParagraphStyle('contact', fontSize=7.5, leading=11, textColor=GREY, alignment=TA_CENTER, fontName='Helvetica', wordWrap='CJK'),
        'h2':      ParagraphStyle('h2',      fontSize=9.5, leading=13, textColor=DARK, fontName='Helvetica-Bold', spaceBefore=7, spaceAfter=2),
        'h3':      ParagraphStyle('h3',      fontSize=9,   leading=12, textColor=ACCENT, fontName='Helvetica-Bold', spaceBefore=5, spaceAfter=1),
        'body':    ParagraphStyle('body',    fontSize=8.5, leading=12, leftIndent=2, textColor=TGREY, fontName='Helvetica', wordWrap='CJK'),
        'bullet':  ParagraphStyle('bullet',  fontSize=8.5, leading=12, leftIndent=14, firstLineIndent=-8, textColor=TGREY, fontName='Helvetica', wordWrap='CJK'),
        'italic':  ParagraphStyle('italic',  fontSize=8,   leading=11, textColor=GREY, fontName='Helvetica-Oblique'),
        'tbl':     ParagraphStyle('tbl',     fontSize=7.5, leading=10, textColor=TGREY, fontName='Helvetica', wordWrap='CJK'),
        'tblh':    ParagraphStyle('tblh',    fontSize=7.5, leading=10, textColor=DARK, fontName='Helvetica-Bold', wordWrap='CJK'),
    }


def _inline(text: str) -> str:
    """Convert inline markdown → reportlab XML. Preserve links as <link> tags."""
    # Links: [display](url) → <link href="url">display</link>
    def link_sub(m):
        display = m.group(1).replace('&', '&amp;')
        url = m.group(2)
        return f'<link href="{url}" color="#2563eb">{display}</link>'

    text = re.sub(r'\[([^\]]+)\]\(([^)]+)\)', link_sub, text)
    text = re.sub(r'\*\*([^*]+)\*\*', r'<b>\1</b>', text)
    text = re.sub(r'\*([^*]+)\*', r'<i>\1</i>', text)
    text = re.sub(r'`([^`]+)`', r'<font name="Courier" size="8">\1</font>', text)
    text = text.replace('&', '&amp;').replace('&amp;amp;', '&amp;')
    # Fix double-escaped from link_sub
    return text


def _inline_contact(text: str) -> str:
    """Contact line — show display text as link, show full URL if display is email."""
    parts = text.split(' · ')
    result_parts = []
    for p in parts:
        p = p.strip()
        m = re.match(r'\[([^\]]+)\]\(([^)]+)\)', p)
        if m:
            display, url = m.group(1), m.group(2)
            result_parts.append(f'<link href="{url}" color="#2563eb">{display}</link>')
        elif re.match(r'^[\w.+-]+@[\w.-]+\.[a-z]{2,}$', p):
            result_parts.append(f'<link href="mailto:{p}" color="#2563eb">{p}</link>')
        else:
            result_parts.append(p)
    return ' · '.join(result_parts)


def md_to_pdf(md_path: str, pdf_path: str) -> str:
    text = Path(md_path).read_text()
    lines = text.splitlines()
    ST = _styles()

    doc = SimpleDocTemplate(
        pdf_path, pagesize=A4,
        leftMargin=14*mm, rightMargin=14*mm,
        topMargin=11*mm, bottomMargin=11*mm,
    )

    story = []
    i = 0
    PAGE_W = A4[0] - 28*mm

    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        # H1 — name
        if line.startswith('# '):
            story.append(Paragraph(line[2:].strip(), ST['name']))
            i += 1; continue

        # Bold-only title line near top
        if line.startswith('**') and line.endswith('**') and not stripped.startswith('**To:**') and i < 6:
            story.append(Paragraph(_inline(stripped), ST['title']))
            story.append(Spacer(1, 1.5*mm))
            i += 1; continue

        # Contact line (contains · separators)
        if '·' in line and ('@' in line or 'github' in line.lower() or 'linkedin' in line.lower()):
            story.append(Paragraph(_inline_contact(line.strip()), ST['contact']))
            story.append(Spacer(1, 0.5*mm))
            i += 1; continue

        # HR
        if stripped == '---':
            story.append(HRFlowable(width='100%', thickness=0.4, color=colors.HexColor('#cccccc'), spaceAfter=2, spaceBefore=2))
            i += 1; continue

        # H2
        if line.startswith('## '):
            story.append(Paragraph(line[3:].strip().upper(), ST['h2']))
            i += 1; continue

        # H3
        if line.startswith('### '):
            story.append(Paragraph(_inline(line[4:].strip()), ST['h3']))
            i += 1; continue

        # Table (detect by | header followed by |---|)
        if stripped.startswith('|') and i + 1 < len(lines) and '---' in lines[i + 1]:
            header_cells = [c.strip() for c in stripped.strip('|').split('|')]
            col_count = len(header_cells)
            i += 2  # skip header + separator row
            rows = [header_cells]
            while i < len(lines) and lines[i].strip().startswith('|'):
                cells = [_inline(c.strip()) for c in lines[i].strip('|').split('|')]
                # Pad/trim to col_count
                while len(cells) < col_count: cells.append('')
                cells = cells[:col_count]
                rows.append(cells)
                i += 1

            # Convert cells to Paragraphs for word-wrap
            para_rows = []
            for ri, row in enumerate(rows):
                sty = ST['tblh'] if ri == 0 else ST['tbl']
                para_rows.append([Paragraph(c, sty) for c in row])

            # Smart column widths
            if col_count == 2:
                col_widths = [PAGE_W * 0.28, PAGE_W * 0.72]
            elif col_count == 3:
                col_widths = [PAGE_W * 0.32, PAGE_W * 0.38, PAGE_W * 0.30]
            else:
                col_widths = [PAGE_W / col_count] * col_count

            t = Table(para_rows, colWidths=col_widths, repeatRows=1)
            t.setStyle(TableStyle([
                ('FONTNAME',    (0, 0), (-1,  0), 'Helvetica-Bold'),
                ('FONTSIZE',    (0, 0), (-1, -1), 7.5),
                ('ROWBACKGROUNDS', (0, 0), (-1, -1), [LGREY, colors.white]),
                ('GRID',        (0, 0), (-1, -1), 0.25, colors.HexColor('#dddddd')),
                ('VALIGN',      (0, 0), (-1, -1), 'TOP'),
                ('LEFTPADDING', (0, 0), (-1, -1), 4),
                ('RIGHTPADDING',(0, 0), (-1, -1), 4),
                ('TOPPADDING',  (0, 0), (-1, -1), 3),
                ('BOTTOMPADDING',(0, 0),(-1, -1), 3),
            ]))
            story.append(t)
            story.append(Spacer(1, 2*mm))
            continue

        # Bullet
        if stripped.startswith('- '):
            content = _inline(stripped[2:])
            story.append(Paragraph(f'• {content}', ST['bullet']))
            i += 1; continue

        # Italic line
        if stripped.startswith('*') and stripped.endswith('*') and not stripped.startswith('**'):
            story.append(Paragraph(_inline(stripped), ST['italic']))
            i += 1; continue

        # Empty line
        if not stripped:
            story.append(Spacer(1, 1*mm))
            i += 1; continue

        # Normal paragraph (bold check for metadata lines)
        if stripped.startswith('**') and stripped.endswith('**'):
            story.append(Paragraph(_inline(stripped), ST['body']))
        else:
            story.append(Paragraph(_inline(stripped), ST['body']))
        i += 1

    doc.build(story)
    return pdf_path


def _add_publications_section(md_text: str, publications: list) -> str:
    """Inject publications into markdown if not already present."""
    if '## WRITING' in md_text.upper() or '## PUBLICATIONS' in md_text.upper():
        return md_text
    if not publications:
        return md_text

    section = "\n\n## WRITING & PUBLICATIONS\n\n"
    for pub in publications:
        title = pub.get('title', '')
        url = pub.get('url', '')
        platform = pub.get('platform', '')
        if url:
            section += f"- [{title}]({url}) — {platform}\n"
        else:
            section += f"- {title} — {platform}\n"

    # Insert before ACHIEVEMENTS section if present
    if '## ACHIEVEMENTS' in md_text:
        return md_text.replace('## ACHIEVEMENTS', section + '\n## ACHIEVEMENTS')
    return md_text + section


if __name__ == '__main__':
    if len(sys.argv) < 3:
        print("Usage: python3 md_to_pdf.py input.md output.pdf")
        sys.exit(1)
    out = md_to_pdf(sys.argv[1], sys.argv[2])
    print(f"PDF: {out}")
