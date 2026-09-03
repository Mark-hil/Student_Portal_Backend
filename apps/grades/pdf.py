"""
PDF Transcript Generator with Unofficial Watermark.
Uses ReportLab to generate academic transcripts with a prominent diagonal watermark.
"""
import io
from decimal import Decimal
from django.utils import timezone
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.units import inch
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, KeepTogether, HRFlowable
)
from reportlab.pdfgen import canvas


class WatermarkedCanvas(canvas.Canvas):
    """Custom canvas that draws a prominent diagonal watermark and page numbers on every page."""
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._saved_page_states = []

    def showPage(self):
        self._saved_page_states.append(dict(self.__dict__))
        self._startPage()

    def save(self):
        num_pages = len(self._saved_page_states)
        for state in self._saved_page_states:
            self.__dict__.update(state)
            self.draw_watermark_and_footer(num_pages)
            super().showPage()
        super().save()

    def draw_watermark_and_footer(self, total_pages: int):
        self.saveState()
        w, h = letter

        # ── Diagonal Watermark ────────────────────────────────────────────────
        self.saveState()
        self.setFont("Helvetica-Bold", 46)
        # Translucent slate gray
        try:
            self.setFillColor(colors.HexColor("#64748b"), alpha=0.13)
        except Exception:
            self.setFillColor(colors.HexColor("#cbd5e1"))
        self.translate(w / 2.0, h / 2.0)
        self.rotate(42)
        self.drawCentredString(0, 0, "UNOFFICIAL TRANSCRIPT")
        self.drawCentredString(0, -70, "FOR ADVISING ONLY")
        self.restoreState()

        # ── Top Warning Banner ────────────────────────────────────────────────
        self.setFont("Helvetica-Bold", 8)
        self.setFillColor(colors.HexColor("#dc2626"))
        self.drawCentredString(w / 2.0, h - 28, "••• UNOFFICIAL RECORD — NOT FOR OFFICIAL CERTIFICATION OR TRANSFER PURPOSES •••")

        # ── Footer ────────────────────────────────────────────────────────────
        self.setStrokeColor(colors.HexColor("#e2e8f0"))
        self.setLineWidth(0.75)
        self.line(40, 42, w - 40, 42)

        self.setFont("Helvetica", 8)
        self.setFillColor(colors.HexColor("#64748b"))
        self.drawString(40, 30, f"UniPortal Academic Affairs • Issued {timezone.now().strftime('%b %d, %Y %H:%M UTC')} • Document ID: REF-{self._pageNumber}")
        self.drawRightString(w - 40, 30, f"Page {self._pageNumber} of {total_pages}")

        self.restoreState()


def build_transcript_pdf(student, semesters_data: list, cumulative_stats: dict) -> io.BytesIO:
    """
    Generates the binary PDF stream for a student's unofficial transcript.
    """
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=letter,
        leftMargin=40,
        rightMargin=40,
        topMargin=46,
        bottomMargin=54,
    )

    styles = getSampleStyleSheet()
    
    # Custom Typography Styles
    title_style = ParagraphStyle(
        "DocTitle",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=18,
        leading=22,
        textColor=colors.HexColor("#0f172a"),
    )
    sub_style = ParagraphStyle(
        "DocSub",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=11,
        leading=15,
        textColor=colors.HexColor("#4f46e5"),
    )
    section_heading = ParagraphStyle(
        "SecHead",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=11,
        leading=14,
        textColor=colors.HexColor("#0f172a"),
    )
    body_bold = ParagraphStyle(
        "BodyBold",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=8.5,
        leading=11,
        textColor=colors.HexColor("#1e293b"),
    )
    body_style = ParagraphStyle(
        "BodyNorm",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=8.5,
        leading=11,
        textColor=colors.HexColor("#334155"),
    )
    small_muted = ParagraphStyle(
        "SmallMuted",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=7.5,
        leading=10,
        textColor=colors.HexColor("#64748b"),
    )

    story = []

    # ── 1. Header Banner ───────────────────────────────────────────────────────
    header_data = [
        [
            Paragraph("<b>UNIPORTAL UNIVERSITY</b>", title_style),
            Paragraph("<b>ACADEMIC TRANSCRIPT</b><br/><font color='#dc2626'>[ UNOFFICIAL RECORD ]</font>", ParagraphStyle(
                "HeaderRight", parent=title_style, fontSize=13, leading=16, alignment=2, textColor=colors.HexColor("#0f172a")
            )),
        ],
        [
            Paragraph("Office of the University Registrar • Academic Records Division", small_muted),
            Paragraph(f"Date Issued: {timezone.now().strftime('%B %d, %Y')}", ParagraphStyle(
                "DateRight", parent=small_muted, alignment=2
            )),
        ]
    ]
    header_table = Table(header_data, colWidths=[3.6 * inch, 3.7 * inch])
    header_table.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 1),
        ("TOPPADDING", (0, 0), (-1, -1), 0),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
    ]))
    story.append(header_table)
    story.append(HRFlowable(width="100%", thickness=1.5, color=colors.HexColor("#4f46e5"), spaceAfter=10, spaceBefore=6))

    # ── 2. Student Information Card ───────────────────────────────────────────
    full_name = student.full_name or student.email
    student_id = student.student_id or "—"
    department = student.department or "Undergraduate Studies"
    cum_gpa = cumulative_stats.get("cumulative_gpa") or "N/A"
    total_cr = cumulative_stats.get("cumulative_credits_earned", 0)

    standing = "Good Standing"
    try:
        if cum_gpa != "N/A" and float(cum_gpa) >= 3.8:
            standing = "President's Honor List"
        elif cum_gpa != "N/A" and float(cum_gpa) >= 3.5:
            standing = "Dean's Honor List"
        elif cum_gpa != "N/A" and float(cum_gpa) < 2.0:
            standing = "Academic Warning"
    except Exception:
        pass

    info_data = [
        [
            Paragraph(f"<b>Student Name:</b> {full_name}", body_style),
            Paragraph(f"<b>Student ID:</b> {student_id}", body_style),
        ],
        [
            Paragraph(f"<b>Department / Major:</b> {department}", body_style),
            Paragraph(f"<b>Email:</b> {student.email}", body_style),
        ],
        [
            Paragraph(f"<b>Cumulative GPA:</b> <b>{cum_gpa}</b>", body_style),
            Paragraph(f"<b>Academic Standing:</b> <font color='#4f46e5'><b>{standing}</b></font>", body_style),
        ],
    ]
    info_table = Table(info_data, colWidths=[3.65 * inch, 3.65 * inch])
    info_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#f8fafc")),
        ("BOX", (0, 0), (-1, -1), 1, colors.HexColor("#cbd5e1")),
        ("INNERGRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#e2e8f0")),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("LEFTPADDING", (0, 0), (-1, -1), 10),
        ("RIGHTPADDING", (0, 0), (-1, -1), 10),
    ]))
    story.append(info_table)
    story.append(Spacer(1, 14))

    # ── 3. Semesters & Courses Breakdown ───────────────────────────────────────
    if not semesters_data:
        story.append(Paragraph("<i>No course grade records currently on file for this student.</i>", body_style))
    else:
        for sem in semesters_data:
            sem_label = sem.get("label") or sem.get("semester") or "Academic Term"
            sem_gpa = sem.get("semester_gpa", "—")
            sem_attempted = sem.get("credits_attempted", 0)
            sem_earned = sem.get("credits_earned", 0)

            # Term Header
            sem_elements = []
            sem_elements.append(Paragraph(f"<b>{sem_label}</b>", section_heading))
            sem_elements.append(Spacer(1, 4))

            # Table Data
            course_rows = [
                [
                    Paragraph("<b>Course</b>", body_bold),
                    Paragraph("<b>Title</b>", body_bold),
                    Paragraph("<b>Att.</b>", body_bold),
                    Paragraph("<b>Earn.</b>", body_bold),
                    Paragraph("<b>Score %</b>", body_bold),
                    Paragraph("<b>Grade</b>", body_bold),
                    Paragraph("<b>Points</b>", body_bold),
                    Paragraph("<b>Quality Pts</b>", body_bold),
                ]
            ]

            for c in sem.get("courses", []):
                course_code = c.get("course_code") or (c.get("course", {}).get("code") if isinstance(c.get("course"), dict) else "—")
                course_title = c.get("course_title") or (c.get("course", {}).get("title") if isinstance(c.get("course"), dict) else "Course")
                att = str(c.get("credits_attempted", 0))
                earn = str(c.get("credits_earned", 0))
                score_val = c.get("score_percentage")
                score_str = f"{float(score_val):.1f}%" if score_val is not None else "—"
                grade = str(c.get("final_grade", "—"))
                pts = str(c.get("grade_points") if c.get("grade_points") is not None else "—")
                qp = str(c.get("quality_points") if c.get("quality_points") is not None else "—")

                course_rows.append([
                    Paragraph(course_code, body_bold),
                    Paragraph(course_title, body_style),
                    Paragraph(att, body_style),
                    Paragraph(earn, body_style),
                    Paragraph(score_str, body_style),
                    Paragraph(f"<b>{grade}</b>", body_style),
                    Paragraph(pts, body_style),
                    Paragraph(qp, body_style),
                ])

            # Term Summary Row
            course_rows.append([
                Paragraph(f"<b>TERM TOTALS:</b> Att: {sem_attempted} | Earned: {sem_earned}", body_bold),
                Paragraph("", body_style),
                Paragraph("", body_style),
                Paragraph("", body_style),
                Paragraph("", body_style),
                Paragraph("", body_style),
                Paragraph("<b>TERM GPA:</b>", body_bold),
                Paragraph(f"<b>{sem_gpa}</b>", body_bold),
            ])

            col_widths = [0.95 * inch, 2.35 * inch, 0.5 * inch, 0.5 * inch, 0.7 * inch, 0.65 * inch, 0.7 * inch, 0.95 * inch]
            sem_table = Table(course_rows, colWidths=col_widths, repeatRows=1)
            sem_table.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#eef2ff")),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3.5),
                ("TOPPADDING", (0, 0), (-1, -1), 3.5),
                ("LEFTPADDING", (0, 0), (-1, -1), 5),
                ("RIGHTPADDING", (0, 0), (-1, -1), 5),
                ("GRID", (0, 0), (-1, -2), 0.5, colors.HexColor("#e2e8f0")),
                ("BACKGROUND", (0, -1), (-1, -1), colors.HexColor("#f1f5f9")),
                ("SPAN", (0, -1), (5, -1)),
                ("LINEABOVE", (0, -1), (-1, -1), 1, colors.HexColor("#cbd5e1")),
                ("LINEBELOW", (0, -1), (-1, -1), 1, colors.HexColor("#cbd5e1")),
            ]))

            sem_elements.append(sem_table)
            sem_elements.append(Spacer(1, 10))
            story.append(KeepTogether(sem_elements))

    # ── 4. Cumulative Summary Box ─────────────────────────────────────────────
    cum_rows = [
        [
            Paragraph("<b>CUMULATIVE ACADEMIC SUMMARY</b>", ParagraphStyle("CumHead", parent=body_bold, textColor=colors.HexColor("#1e1b4b"), fontSize=9.5)),
            Paragraph("", body_style),
        ],
        [
            Paragraph(f"<b>Total Credits Attempted:</b> {cumulative_stats.get('cumulative_credits_attempted', 0)}", body_style),
            Paragraph(f"<b>Cumulative GPA:</b> <b><font size=10 color='#4f46e5'>{cum_gpa}</font></b>", body_style),
        ],
        [
            Paragraph(f"<b>Total Credits Earned:</b> {total_cr}", body_style),
            Paragraph(f"<b>Total Quality Points:</b> {cumulative_stats.get('cumulative_quality_points', 0)}", body_style),
        ],
    ]
    cum_table = Table(cum_rows, colWidths=[3.65 * inch, 3.65 * inch])
    cum_table.setStyle(TableStyle([
        ("SPAN", (0, 0), (1, 0)),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e0e7ff")),
        ("BACKGROUND", (0, 1), (-1, -1), colors.HexColor("#f8fafc")),
        ("BOX", (0, 0), (-1, -1), 1, colors.HexColor("#c7d2fe")),
        ("INNERGRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#e2e8f0")),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("LEFTPADDING", (0, 0), (-1, -1), 10),
        ("RIGHTPADDING", (0, 0), (-1, -1), 10),
    ]))
    story.append(Spacer(1, 6))
    story.append(KeepTogether([cum_table]))

    # ── 5. Grading Scale & Advisory Notice ─────────────────────────────────────
    notice_text = (
        "<b>GRADING SYSTEM & POLICY:</b><br/>"
        "A/A+ = 4.0 | A- = 3.7 | B+ = 3.3 | B = 3.0 | B- = 2.7 | C+ = 2.3 | C = 2.0 | C- = 1.7 | D+ = 1.3 | D = 1.0 | D- = 0.7 | F = 0.0<br/>"
        "<i>Notice: This document is an UNOFFICIAL academic transcript generated by the student information system. "
        "Official transcripts must bear the seal of the University and the signature of the Registrar.</i>"
    )
    story.append(Spacer(1, 12))
    story.append(Paragraph(notice_text, small_muted))

    # Build PDF using our custom canvas with the watermark
    doc.build(story, canvasmaker=WatermarkedCanvas)
    buffer.seek(0)
    return buffer
