"""PDF report generation for PRISMA."""
from io import BytesIO

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle


def build_pdf(resultats, decision, score, title="Rapport de conformité PRISMA"):
    output = BytesIO()
    document = SimpleDocTemplate(
        output, pagesize=A4, rightMargin=18 * mm, leftMargin=18 * mm,
        topMargin=16 * mm, bottomMargin=16 * mm,
    )
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(name="Cover", parent=styles["Title"], alignment=TA_CENTER,
                               textColor=colors.HexColor("#16324F"), spaceAfter=10 * mm))
    styles.add(ParagraphStyle(name="Small", parent=styles["BodyText"], fontSize=8, leading=10))
    styles.add(ParagraphStyle(name="Cell", parent=styles["BodyText"], fontSize=8, leading=10))
    story = [Paragraph(title, styles["Cover"]),
             Paragraph(f"Décision : <b>{decision['titre']}</b>", styles["Heading2"]),
             Paragraph(decision["message"], styles["BodyText"]), Spacer(1, 5 * mm),
             Paragraph(f"Score global : <b>{score} %</b>", styles["Heading2"]), Spacer(1, 5 * mm)]

    rows = [["ID", "Exigence", "Verdict", "Source / action"]]
    for item in resultats:
        source = ""
        if item.get("document"):
            source = f"{item['document']} p.{item.get('page', '?')}"
        if item.get("action"):
            source = f"{source} — {item['action']}" if source else item["action"]
        rows.append([
            item.get("id", ""),
            Paragraph(str(item.get("texte", "")), styles["Cell"]),
            item.get("verdict", ""),
            Paragraph(source, styles["Cell"]),
        ])
    table = Table(rows, colWidths=[18 * mm, 72 * mm, 25 * mm, 57 * mm], repeatRows=1)
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#16324F")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#CBD5E1")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F1F5F9")]),
        ("PADDING", (0, 0), (-1, -1), 5),
    ]))
    story.append(table)
    story.append(Spacer(1, 6 * mm))
    story.append(Paragraph("Document généré par PRISMA. Les verdicts doivent être relus avant tout dépôt officiel.", styles["Small"]))
    document.build(story)
    return output.getvalue()
