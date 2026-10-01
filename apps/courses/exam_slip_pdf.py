"""
Official Examination Clearance Slip & Candidate Docket PDF Generator.
Generated via ReportLab with institutional branding, security QR code, 
registered course verification table, and financial clearance authentication.
"""
import io
import uuid
from decimal import Decimal
from django.utils import timezone
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.units import inch
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable
)
from reportlab.pdfgen import canvas
from reportlab.graphics.shapes import Drawing
from reportlab.graphics.barcode import qr


class ExamSlipCanvas(canvas.Canvas):
    """Custom canvas that draws institutional security watermark and verification footer."""
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
            self.draw_page_decorations()
            super().showPage()
        super().save()

    def draw_page_decorations(self):
        self.saveState()
        w, h = letter

        # ── Subtle Institutional Watermark ────────────────────────────────────
        self.saveState()
        self.setFont("Helvetica-Bold", 42)
        try:
            self.setFillColor(colors.HexColor("#064e3b"), alpha=0.04)
        except Exception:
            self.setFillColor(colors.HexColor("#f1f5f9"))
        self.translate(w / 2.0, h / 2.0)
        self.rotate(35)
        self.drawCentredString(0, 0, "OFFICIAL EXAMINATION DOCKET")
        self.drawCentredString(0, -50, "ASDAM COLLEGE OF HEALTH SCIENCES")
        self.restoreState()

        # ── Institutional Outer Security Border ────────────────────────────────
        self.setStrokeColor(colors.HexColor("#064e3b"))
        self.setLineWidth(1.5)
        self.rect(24, 24, w - 48, h - 48)

        self.setStrokeColor(colors.HexColor("#eab308"))
        self.setLineWidth(0.75)
        self.rect(27, 27, w - 54, h - 54)

        # ── Bottom Security Footer ─────────────────────────────────────────────
        self.setFont("Helvetica-Bold", 7.5)
        self.setFillColor(colors.HexColor("#064e3b"))
        self.drawString(34, 34, "ASDAM DIRECTORATE OF EXAMINATIONS • OFFICIAL ACADEMIC CLEARANCE")
        self.setFont("Helvetica", 7)
        self.setFillColor(colors.HexColor("#64748b"))
        self.drawRightString(w - 34, 34, f"Valid for Registered Examinations • Generated {timezone.now().strftime('%d/%m/%Y %H:%M UTC')}")

        self.restoreState()


def build_exam_slip_pdf(student, enrollments: list, clearance_info: dict) -> io.BytesIO:
    """
    Generates an official, single-page printable Examination Clearance Slip & Hall Ticket.
    """
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=letter,
        leftMargin=34,
        rightMargin=34,
        topMargin=34,
        bottomMargin=42,
    )

    styles = getSampleStyleSheet()

    # ── Typography Styles ──────────────────────────────────────────────────────
    col_primary = colors.HexColor("#064e3b")  # Deep Forest Green
    col_gold = colors.HexColor("#ca8a04")     # Academic Gold

    inst_title = ParagraphStyle(
        "InstTitle",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=13,
        leading=16,
        textColor=col_primary,
        alignment=1,
    )
    doc_title = ParagraphStyle(
        "DocTitle",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=11,
        leading=14,
        textColor=colors.HexColor("#1e293b"),
        alignment=1,
    )
    sub_title = ParagraphStyle(
        "SubTitle",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=8.5,
        leading=11,
        textColor=col_gold,
        alignment=1,
    )
    label_bold = ParagraphStyle(
        "LabelBold",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=8,
        leading=10,
        textColor=colors.HexColor("#1e293b"),
    )
    val_norm = ParagraphStyle(
        "ValNorm",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=8,
        leading=10,
        textColor=colors.HexColor("#334155"),
    )
    th_style = ParagraphStyle(
        "THStyle",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=7.5,
        leading=10,
        textColor=colors.white,
        alignment=1,
    )
    td_style = ParagraphStyle(
        "TDStyle",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=7.5,
        leading=10,
        textColor=colors.HexColor("#1e293b"),
    )
    td_center = ParagraphStyle(
        "TDCenter",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=7.5,
        leading=10,
        textColor=colors.HexColor("#1e293b"),
        alignment=1,
    )

    story = []

    # ── 1. Institutional Header ───────────────────────────────────────────────
    story.append(Paragraph("ASDAM COLLEGE OF HEALTH SCIENCES", inst_title))
    story.append(Paragraph("DIRECTORATE OF ACADEMIC AFFAIRS & EXAMINATIONS", doc_title))
    semester_label = clearance_info.get("semester") or "2024/2025 ACADEMIC YEAR • SEMESTER EXAMINATIONS"
    story.append(Paragraph(f"<b>OFFICIAL CANDIDATE EXAMINATION DOCKET & CLEARANCE SLIP</b> — {semester_label.upper()}", sub_title))
    story.append(Spacer(1, 4))
    story.append(HRFlowable(width="100%", thickness=1.5, color=col_primary, spaceAfter=2, spaceBefore=2))
    story.append(HRFlowable(width="100%", thickness=0.75, color=colors.HexColor("#eab308"), spaceAfter=6, spaceBefore=0))

    # ── 2. QR Code & Photo Box Generation ──────────────────────────────────────
    student_id = student.student_id or "UNASSIGNED"
    full_name = student.full_name or student.email
    clearance_ref = clearance_info.get("reference", f"CLR-{uuid.uuid4().hex[:8].upper()}")

    qr_data = f"ASDAM-EXAM-VERIFIED|ID:{student_id}|STU:{full_name}|STATUS:CLEARED|REF:{clearance_ref}|GEN:{timezone.now().strftime('%Y%m%d%H%M')}"
    qr_widget = qr.QrCodeWidget(qr_data)
    bounds = qr_widget.getBounds()
    qw = bounds[2] - bounds[0]
    qh = bounds[3] - bounds[1]
    qr_drawing = Drawing(68, 68, transform=[68.0 / qw, 0, 0, 68.0 / qh, 0, 0])
    qr_drawing.add(qr_widget)

    # ── 3. Student Bio & Clearance Status Card ─────────────────────────────────
    program_display = student.get_program_display() if hasattr(student, "get_program_display") else (student.program or "General Nursing")
    if not program_display or program_display == "":
        program_display = "Nursing & Midwifery Sciences"
    class_level = student.class_name if student.class_name else "100"
    moh_pin = student.moh_pin or "N/A"
    balance_due = clearance_info.get("balance", Decimal("0.00"))

    # Student Info grid + QR Code + Photo Placeholder
    student_meta_data = [
        [
            Paragraph("<b>Candidate Name:</b>", label_bold),
            Paragraph(f"<b>{full_name.upper()}</b>", label_bold),
            Paragraph("<b>Student Index / ID:</b>", label_bold),
            Paragraph(f"<b>{student_id}</b>", label_bold),
            qr_drawing,
        ],
        [
            Paragraph("<b>Program of Study:</b>", label_bold),
            Paragraph(f"{program_display}", val_norm),
            Paragraph("<b>Class / Academic Level:</b>", label_bold),
            Paragraph(f"Level {class_level}", val_norm),
            "",
        ],
        [
            Paragraph("<b>MOH / Nursing PIN:</b>", label_bold),
            Paragraph(f"{moh_pin}", val_norm),
            Paragraph("<b>Clearance Docket Ref:</b>", label_bold),
            Paragraph(f"<font color='#064e3b'><b>{clearance_ref}</b></font>", val_norm),
            "",
        ],
        [
            Paragraph("<b>Financial Clearance:</b>", label_bold),
            Paragraph("<font color='#059669'><b>CLEARED (EXAM ELIGIBLE)</b></font>", label_bold),
            Paragraph("<b>Outstanding Balance:</b>", label_bold),
            Paragraph(f"GH₵ {balance_due:,.2f}", val_norm),
            "",
        ]
    ]

    meta_table = Table(
        student_meta_data,
        colWidths=[1.3 * inch, 2.2 * inch, 1.4 * inch, 1.6 * inch, 1.0 * inch]
    )
    meta_table.setStyle(TableStyle([
        ("SPAN", (4, 0), (4, 3)),  # QR code spans 4 rows
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ALIGN", (4, 0), (4, 3), "CENTER"),
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#f8fafc")),
        ("BOX", (0, 0), (-1, -1), 0.75, colors.HexColor("#cbd5e1")),
        ("INNERGRID", (0, 0), (3, -1), 0.5, colors.HexColor("#e2e8f0")),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
    ]))
    story.append(meta_table)
    story.append(Spacer(1, 8))

    # ── 4. Registered Courses Verification Table ──────────────────────────────
    course_rows = [
        [
            Paragraph("<b>#</b>", th_style),
            Paragraph("<b>Course Code</b>", th_style),
            Paragraph("<b>Course Title</b>", th_style),
            Paragraph("<b>Credits</b>", th_style),
            Paragraph("<b>Schedule / Hall</b>", th_style),
            Paragraph("<b>Invigilator's Sign & Script No.</b>", th_style),
        ]
    ]

    total_credits = 0
    idx = 1
    for enr in enrollments:
        c = enr.course
        cr = c.credits or 3
        total_credits += cr
        sched_text = "Main Hall / TBA"
        schedules = list(c.schedules.all()[:1]) if hasattr(c, "schedules") else []
        if schedules:
            sc = schedules[0]
            sched_text = f"{sc.get_day_of_week_display()[:3]} {sc.start_time.strftime('%H:%M')}"
            if sc.room:
                sched_text += f" ({sc.room})"

        course_rows.append([
            Paragraph(str(idx), td_center),
            Paragraph(f"<b>{c.code}</b>", td_center),
            Paragraph(c.title, td_style),
            Paragraph(str(cr), td_center),
            Paragraph(sched_text, td_style),
            Paragraph("[ &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; ]", td_center),
        ])
        idx += 1

    # Total credits summary row
    course_rows.append([
        Paragraph("", td_center),
        Paragraph("<b>TOTAL</b>", td_center),
        Paragraph("<b>Total Approved Examination Course Units</b>", td_style),
        Paragraph(f"<b>{total_credits}</b>", td_center),
        Paragraph("<b>ALL ELIGIBLE</b>", td_center),
        Paragraph("", td_center),
    ])

    course_table = Table(
        course_rows,
        colWidths=[0.35 * inch, 1.15 * inch, 2.65 * inch, 0.65 * inch, 1.25 * inch, 1.45 * inch]
    )
    t_style = [
        ("BACKGROUND", (0, 0), (-1, 0), col_primary),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("ALIGN", (0, 0), (-1, 0), "CENTER"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("BOX", (0, 0), (-1, -1), 0.75, colors.HexColor("#064e3b")),
        ("INNERGRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#e2e8f0")),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("BACKGROUND", (0, -1), (-1, -1), colors.HexColor("#f1f5f9")),
    ]
    # Alternating row colors
    for r in range(1, len(course_rows) - 1):
        bg = colors.white if r % 2 == 1 else colors.HexColor("#f8fafc")
        t_style.append(("BACKGROUND", (0, r), (-1, r), bg))

    course_table.setStyle(TableStyle(t_style))
    story.append(course_table)
    story.append(Spacer(1, 8))

    # ── 5. Examination Rules & Directives ─────────────────────────────────────
    rules_text = Paragraph(
        "<b>MANDATORY CANDIDATE EXAMINATION DIRECTIVES:</b><br/>"
        "1. This docket MUST be printed and displayed on the candidate's desk alongside a valid ASDAM Student ID card at every session.<br/>"
        "2. Invigilators will cross-reference candidate identity and initial this slip upon entry and when scripts are collected.<br/>"
        "3. Mobile phones, programmable watches, bags, and unauthorized materials are STRICTLY PROHIBITED in the exam hall.<br/>"
        "4. Any mutilation, unauthorized alteration, or impersonation constitutes grave examination malpractice subject to expulsion.",
        ParagraphStyle("RulesStyle", parent=styles["Normal"], fontSize=6.8, leading=9.5, textColor=colors.HexColor("#334155"))
    )
    rules_table = Table([[rules_text]], colWidths=[7.5 * inch])
    rules_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#fef2f2")),
        ("BOX", (0, 0), (-1, -1), 0.75, colors.HexColor("#fca5a5")),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
    ]))
    story.append(rules_table)
    story.append(Spacer(1, 10))

    # ── 6. Verification & Signatures ──────────────────────────────────────────
    sig_data = [
        [
            Paragraph("<b>Candidate's Attestation:</b><br/><i>I certify that all details above are accurate and I agree to all exam bylaws.</i><br/><br/>________________________________________<br/>Candidate's Signature & Date", ParagraphStyle("Sig1", parent=styles["Normal"], fontSize=7.2, leading=9.5, textColor=colors.HexColor("#1e293b"))),
            Paragraph("<b>Academic Directorate & Examinations Office:</b><br/><i>Validated electronically via ASDAM Student Information System.</i><br/><br/><b>APPROVED FOR SITTING</b><br/><font color='#064e3b'>Director of Academic Affairs & Examinations</font>", ParagraphStyle("Sig2", parent=styles["Normal"], fontSize=7.2, leading=9.5, textColor=colors.HexColor("#1e293b"), alignment=2)),
        ]
    ]
    sig_table = Table(sig_data, colWidths=[4.2 * inch, 3.3 * inch])
    sig_table.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 2),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
    ]))
    story.append(sig_table)

    # Build PDF with custom canvas
    doc.build(story, canvasmaker=ExamSlipCanvas)
    buffer.seek(0)
    return buffer
