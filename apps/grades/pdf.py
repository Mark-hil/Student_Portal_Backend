"""
Official Academic Transcript & Student Performance Dossier PDF Generator.
Engineered with institutional branding, security QR code, dual outer security border,
watermarked canvas, detailed term-by-term grade ledger, cumulative classification,
standard UCC / NMTC grading key, and formal registrar sign-off block.
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
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, KeepTogether, HRFlowable
)
from reportlab.pdfgen import canvas
from reportlab.graphics.shapes import Drawing
from reportlab.graphics.barcode import qr


class TranscriptCanvas(canvas.Canvas):
    """
    Two-pass canvas that applies:
    - Official dual security border in College Forest Green & Academic Gold (or Amber for Unofficial)
    - High-elegance diagonal security watermark (Official vs Unofficial Student Advisory)
    - Microprint security running header
    - Verified document footer with dynamic 'Page X of Y' pagination
    """
    is_official: bool = True
    hold_info: dict = None

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
            self.draw_page_decorations(num_pages)
            super().showPage()
        super().save()

    def draw_page_decorations(self, total_pages: int):
        self.saveState()
        w, h = letter

        # ── 1. Dual Security Outer Border ─────────────────────────────────────
        if self.is_official:
            self.setStrokeColor(colors.HexColor("#064e3b"))
            self.setLineWidth(1.5)
            self.rect(22, 22, w - 44, h - 44)

            self.setStrokeColor(colors.HexColor("#ca8a04"))
            self.setLineWidth(0.6)
            self.rect(25, 25, w - 50, h - 50)
        else:
            self.setStrokeColor(colors.HexColor("#b45309"))
            self.setLineWidth(1.5)
            self.rect(22, 22, w - 44, h - 44)

            self.setStrokeColor(colors.HexColor("#94a3b8"))
            self.setLineWidth(0.6)
            self.rect(25, 25, w - 50, h - 50)

        # ── 2. Diagonal Security Watermark ────────────────────────────────────
        self.saveState()
        if self.is_official:
            self.setFont("Helvetica-Bold", 42)
            try:
                self.setFillColor(colors.HexColor("#064e3b"), alpha=0.13)
            except Exception:
                self.setFillColor(colors.HexColor("#cbd5e1"))
            self.translate(w / 2.0, h / 2.0)
            self.rotate(36)
            self.drawCentredString(0, 45, "OFFICIAL ACADEMIC RECORD")
            self.drawCentredString(0, -10, "S.D.A NMTC ASAMANG - AGONA")
            self.setFont("Helvetica-Bold", 18)
            self.drawCentredString(0, -45, "VALID ONLY WITH EMBOSSED SEAL")
        else:
            self.setFont("Helvetica-Bold", 44)
            try:
                self.setFillColor(colors.HexColor("#d97706"), alpha=0.18)
            except Exception:
                self.setFillColor(colors.HexColor("#fed7aa"))
            self.translate(w / 2.0, h / 2.0)
            self.rotate(36)
            self.drawCentredString(0, 45, "UNOFFICIAL TRANSCRIPT")
            self.setFont("Helvetica-Bold", 26)
            self.drawCentredString(0, 5, "STUDENT ADVISORY COPY ONLY")
            self.setFont("Helvetica-Bold", 16)
            self.drawCentredString(0, -30, "NOT FOR OFFICIAL OR TRANSFER USE")
        self.restoreState()

        # ── 3. Microprint Top Security Header ──────────────────────────────────
        self.setFont("Helvetica-Bold", 7)
        if self.is_official:
            self.setFillColor(colors.HexColor("#064e3b"))
            self.drawCentredString(
                w / 2.0,
                h - 18,
                "••• S.D.A. NURSING & MIDWIFERY TRAINING COLLEGE • OFFICIAL TRANSCRIPT OF ACADEMIC RECORD •••"
            )
        else:
            self.setFillColor(colors.HexColor("#b45309"))
            self.drawCentredString(
                w / 2.0,
                h - 18,
                "••• S.D.A. NURSING & MIDWIFERY TRAINING COLLEGE • UNOFFICIAL STUDENT ADVISORY RECORD •••"
            )

        # ── 4. Official Footer & Verification Banner ──────────────────────────
        self.setStrokeColor(colors.HexColor("#cbd5e1"))
        self.setLineWidth(0.6)
        self.line(34, 38, w - 34, 38)

        self.setFont("Helvetica", 7.5)
        self.setFillColor(colors.HexColor("#475569"))
        timestamp = timezone.now().strftime("%d-%b-%Y %H:%M UTC")
        if self.is_official:
            footer_text = f"Official Academic Dossier • Issued {timestamp} • portal.asdam.edu.gh/verify"
        else:
            footer_text = f"Unofficial Student Copy • Issued {timestamp} • Clear Arrears at Student Financials for Official Record"
        self.drawString(34, 28, footer_text)
        self.drawRightString(w - 34, 28, f"Page {self._pageNumber} of {total_pages}")

        self.restoreState()


def get_degree_classification(gpa_val) -> str:
    """Return official university honours classification from CGPA."""
    try:
        val = float(gpa_val)
        if val >= 3.60:
            return "First Class Honours / Distinction"
        elif val >= 3.00:
            return "Second Class Honours (Upper Division)"
        elif val >= 2.50:
            return "Second Class Honours (Lower Division)"
        elif val >= 2.00:
            return "Third Class Honours"
        elif val >= 1.00:
            return "Pass"
        else:
            return "Fail / Unsatisfactory"
    except (ValueError, TypeError):
        return "In Progress"


def build_transcript_pdf(
    student,
    semesters_data: list,
    cumulative_stats: dict,
    is_official: bool = True,
    hold_info: dict = None,
) -> io.BytesIO:
    """
    Generates a high-fidelity, publication-grade academic transcript PDF for a student.
    Supports official certified records as well as unofficial student advisory copies
    when financial fee arrears exist.
    """
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=letter,
        leftMargin=28,
        rightMargin=28,
        topMargin=20,
        bottomMargin=26,
    )

    styles = getSampleStyleSheet()

    # Brand Colors
    c_primary = colors.HexColor("#064e3b")  # Deep Forest Green
    c_gold = colors.HexColor("#ca8a04")     # Warm Academic Gold
    c_dark = colors.HexColor("#0f172a")     # Slate 900
    c_slate = colors.HexColor("#334155")    # Slate 700
    c_muted = colors.HexColor("#64748b")    # Slate 500

    # Typography Styles
    inst_main = ParagraphStyle(
        "InstMain",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=13,
        leading=16,
        textColor=c_primary,
        alignment=1,
    )
    inst_sub = ParagraphStyle(
        "InstSub",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=9,
        leading=12,
        textColor=c_gold,
        alignment=1,
    )
    inst_affil = ParagraphStyle(
        "InstAffil",
        parent=styles["Normal"],
        fontName="Helvetica-Oblique",
        fontSize=7.5,
        leading=10,
        textColor=c_slate,
        alignment=1,
    )
    doc_heading = ParagraphStyle(
        "DocHeading",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=11,
        leading=14,
        textColor=c_dark,
        alignment=1,
    )

    lbl_bold = ParagraphStyle(
        "LblBold",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=7.5,
        leading=10,
        textColor=c_dark,
    )
    val_norm = ParagraphStyle(
        "ValNorm",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=7.5,
        leading=10,
        textColor=c_slate,
    )

    tbl_th = ParagraphStyle(
        "TblTH",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=7,
        leading=9,
        textColor=colors.white,
        alignment=1,
    )
    tbl_td = ParagraphStyle(
        "TblTD",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=7,
        leading=9,
        textColor=c_dark,
    )
    tbl_td_bold = ParagraphStyle(
        "TblTDBold",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=7,
        leading=9,
        textColor=c_dark,
    )
    tbl_td_center = ParagraphStyle(
        "TblTDCenter",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=7,
        leading=9,
        textColor=c_dark,
        alignment=1,
    )
    tbl_td_center_bold = ParagraphStyle(
        "TblTDCenterBold",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=7,
        leading=9,
        textColor=c_dark,
        alignment=1,
    )

    story = []

    # ── 1. Institutional Header Banner ─────────────────────────────────────────
    story.append(Paragraph("S.D.A. NURSING & MIDWIFERY TRAINING COLLEGE", inst_main))
    story.append(Paragraph("ASAMANG - AGONA, ASHANTI REGION, GHANA", inst_sub))
    story.append(
        Paragraph("Affiliated to the University of Cape Coast (UCC) • Regulated by the Nursing & Midwifery Council of Ghana (NMC)", inst_affil)
    )
    if is_official:
        story.append(Paragraph("OFFICE OF THE REGISTRAR • OFFICIAL ACADEMIC TRANSCRIPT", doc_heading))
    else:
        doc_heading_unoff = ParagraphStyle(
            "DocHeadingUnoff",
            parent=doc_heading,
            textColor=colors.HexColor("#9a3412"),
            fontSize=10.5,
            leading=13,
        )
        story.append(Paragraph("STUDENT ADVISORY RECORD • UNOFFICIAL ACADEMIC TRANSCRIPT", doc_heading_unoff))
        if hold_info and hold_info.get("amount_due"):
            story.append(Spacer(1, 1))
            story.append(
                Paragraph(
                    f"<b>NOTICE:</b> Official certified copy withheld due to semester fee balance of GH¢ {float(hold_info['amount_due']):,.2f}. Clear balance at Student Financials.",
                    ParagraphStyle("HoldNotice", fontName="Helvetica-Bold", fontSize=6.8, leading=8.5, textColor=colors.HexColor("#b91c1c"), alignment=1)
                )
            )

    story.append(Spacer(1, 4))
    story.append(HRFlowable(width="100%", thickness=1.5, color=c_primary if is_official else colors.HexColor("#b45309"), spaceAfter=1.5, spaceBefore=0))
    story.append(HRFlowable(width="100%", thickness=0.75, color=c_gold if is_official else colors.HexColor("#94a3b8"), spaceAfter=7, spaceBefore=0))

    # ── 2. Document Serial & Verification QR Code ──────────────────────────────
    student_id = student.student_id or "UNASSIGNED"
    full_name = student.full_name or student.email
    cum_gpa = str(cumulative_stats.get("cumulative_gpa") or "N/A")
    total_cr_earned = cumulative_stats.get("cumulative_credits_earned", 0)
    total_cr_attempted = cumulative_stats.get("cumulative_credits_attempted", total_cr_earned)
    total_qp = cumulative_stats.get("cumulative_quality_points", "0.00")

    prefix_code = "ASDAM-TR" if is_official else "ASDAM-UNOFF"
    doc_ref = f"{prefix_code}-{uuid.uuid4().hex[:8].upper()}"
    date_issued = timezone.now().strftime("%B %d, %Y")

    status_tag = "OFFICIAL-CERTIFIED" if is_official else "UNOFFICIAL-ADVISORY"
    qr_payload = (
        f"ASDAM-TRANSCRIPT-{status_tag}|DOC:{doc_ref}|ID:{student_id}|"
        f"NAME:{full_name}|CGPA:{cum_gpa}|CREDITS:{total_cr_earned}|DATE:{timezone.now().strftime('%Y%m%d')}"
    )
    qr_widget = qr.QrCodeWidget(qr_payload)
    bounds = qr_widget.getBounds()
    qw = bounds[2] - bounds[0]
    qh = bounds[3] - bounds[1]
    qr_drawing = Drawing(62, 62, transform=[62.0 / qw, 0, 0, 62.0 / qh, 0, 0])
    qr_drawing.add(qr_widget)

    # Student metadata details
    program_name = (
        getattr(student, "program", None) or getattr(student, "department", None) or "Registered General Nursing"
    )
    if hasattr(student, "get_program_display"):
        disp = student.get_program_display()
        if disp:
            program_name = disp
    program_name = str(program_name).title()
    if program_name.lower() in ["nursing", "midwifery"]:
        program_name = f"Diploma in {program_name.title()}"

    moh_pin = getattr(student, "moh_pin", None) or "MOH-NUR-VERIFIED"
    class_level = getattr(student, "class_name", None) or getattr(student, "academic_level", None) or "Level 300"
    if not str(class_level).lower().startswith("level"):
        class_level = f"Level {class_level}"

    classification = get_degree_classification(cum_gpa)

    if is_official:
        standing_str = "<font color='#047857'><b>Good Standing • Certified</b></font>"
    else:
        if hold_info and hold_info.get("amount_due"):
            standing_str = f"<font color='#dc2626'><b>Unofficial • Fee Arrears (GH¢ {float(hold_info['amount_due']):,.2f})</b></font>"
        else:
            standing_str = "<font color='#b45309'><b>Unofficial Record • Advisory Copy</b></font>"

    # Meta card table (2 columns of bio data + right QR code)
    bio_table_data = [
        [
            Paragraph("<b>Candidate Name:</b>", lbl_bold),
            Paragraph(f"<b>{full_name.upper()}</b>", lbl_bold),
            Paragraph("<b>Student Index / ID:</b>", lbl_bold),
            Paragraph(f"<b>{student_id}</b>", lbl_bold),
            qr_drawing,
        ],
        [
            Paragraph("<b>Program of Study:</b>", lbl_bold),
            Paragraph(f"{program_name}", val_norm),
            Paragraph("<b>Class / Academic Level:</b>", lbl_bold),
            Paragraph(f"{class_level}", val_norm),
            "",
        ],
        [
            Paragraph("<b>MOH / Nursing PIN:</b>", lbl_bold),
            Paragraph(f"{moh_pin}", val_norm),
            Paragraph("<b>Document Serial Ref:</b>", lbl_bold),
            Paragraph(f"<font color='{'#064e3b' if is_official else '#9a3412'}'><b>{doc_ref}</b></font>", val_norm),
            "",
        ],
        [
            Paragraph("<b>Cumulative GPA (CGPA):</b>", lbl_bold),
            Paragraph(f"<b><font size=8.5 color='#064e3b'>{cum_gpa} / 4.00</font></b>", lbl_bold),
            Paragraph("<b>Classification Standing:</b>", lbl_bold),
            Paragraph(f"<b><font color='#ca8a04'>{classification}</font></b>", lbl_bold),
            "",
        ],
        [
            Paragraph("<b>Date of Issue:</b>", lbl_bold),
            Paragraph(f"{date_issued}", val_norm),
            Paragraph("<b>Academic Standing:</b>", lbl_bold),
            Paragraph(standing_str, val_norm),
            "",
        ],
    ]

    col_w = [1.3 * inch, 2.35 * inch, 1.4 * inch, 1.65 * inch, 0.9 * inch]
    bio_table = Table(bio_table_data, colWidths=col_w)
    bio_table.setStyle(TableStyle([
        ("SPAN", (4, 0), (4, -1)),  # Span QR code across all rows
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ALIGN", (4, 0), (4, -1), "CENTER"),
        ("VALIGN", (4, 0), (4, -1), "MIDDLE"),
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#f8fafc")),
        ("BOX", (0, 0), (-1, -1), 1, colors.HexColor("#cbd5e1")),
        ("INNERGRID", (0, 0), (3, -1), 0.5, colors.HexColor("#e2e8f0")),
        ("LINEBEFORE", (4, 0), (4, -1), 0.5, colors.HexColor("#cbd5e1")),
        ("TOPPADDING", (0, 0), (-1, -1), 1.8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 1.8),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
    ]))

    story.append(bio_table)
    story.append(Spacer(1, 4))

    # ── 3. Term-by-Term Course Ledger ──────────────────────────────────────────
    if not semesters_data:
        story.append(Paragraph("<i>No course grade records currently on file for this candidate.</i>", val_norm))
    else:
        for sem in semesters_data:
            sem_label = sem.get("label") or sem.get("semester") or "Academic Term"
            sem_gpa = sem.get("semester_gpa", "—")
            sem_attempted = sem.get("credits_attempted", 0)
            sem_earned = sem.get("credits_earned", 0)

            # Compute term quality points
            term_qp_sum = Decimal("0.00")
            for c in sem.get("courses", []):
                qp_val = c.get("quality_points")
                if qp_val is not None:
                    try:
                        term_qp_sum += Decimal(str(qp_val))
                    except Exception:
                        pass

            sem_elements = []

            # Term Header Bar
            term_header_data = [
                [
                    Paragraph(f"<b>ACADEMIC TERM: {sem_label.upper()}</b>", ParagraphStyle(
                        "TermHdrL", fontName="Helvetica-Bold", fontSize=8, leading=10, textColor=colors.white
                    )),
                    Paragraph(
                        f"<b>TERM GPA: {sem_gpa}</b> &nbsp;|&nbsp; CREDITS EARNED: {sem_earned}",
                        ParagraphStyle(
                            "TermHdrR", fontName="Helvetica-Bold", fontSize=8, leading=10, textColor=colors.HexColor("#fef08a"), alignment=2
                        )
                    )
                ]
            ]
            term_hdr_table = Table(term_header_data, colWidths=[4.3 * inch, 3.4 * inch])
            term_hdr_table.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (-1, -1), c_primary),
                ("TOPPADDING", (0, 0), (-1, -1), 2.2),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 2.2),
                ("LEFTPADDING", (0, 0), (-1, -1), 8),
                ("RIGHTPADDING", (0, 0), (-1, -1), 8),
            ]))
            sem_elements.append(term_hdr_table)

            # Course Rows Table
            course_table_rows = [
                [
                    Paragraph("COURSE CODE", tbl_th),
                    Paragraph("COURSE TITLE", tbl_th),
                    Paragraph("ATT. CR", tbl_th),
                    Paragraph("EARN. CR", tbl_th),
                    Paragraph("SCORE (%)", tbl_th),
                    Paragraph("GRADE", tbl_th),
                    Paragraph("GRADE PT", tbl_th),
                    Paragraph("QUALITY PTS", tbl_th),
                ]
            ]

            courses_list = sem.get("courses", [])
            for row_idx, c in enumerate(courses_list):
                course_code = c.get("course_code") or (c.get("course", {}).get("code") if isinstance(c.get("course"), dict) else "—")
                course_title = c.get("course_title") or (c.get("course", {}).get("title") if isinstance(c.get("course"), dict) else "Course Title")
                att = str(c.get("credits_attempted", 0))
                earn = str(c.get("credits_earned", 0))
                score_val = c.get("score_percentage")
                score_str = f"{float(score_val):.1f}%" if score_val is not None else "—"
                grade = str(c.get("final_grade", "—"))
                pts = f"{float(c.get('grade_points')):.2f}" if c.get("grade_points") is not None else "—"
                qp = f"{float(c.get('quality_points')):.2f}" if c.get("quality_points") is not None else "—"

                course_table_rows.append([
                    Paragraph(f"<b>{course_code}</b>", tbl_td_bold),
                    Paragraph(course_title, tbl_td),
                    Paragraph(att, tbl_td_center),
                    Paragraph(earn, tbl_td_center),
                    Paragraph(score_str, tbl_td_center),
                    Paragraph(f"<b>{grade}</b>", tbl_td_center_bold),
                    Paragraph(pts, tbl_td_center),
                    Paragraph(qp, tbl_td_center_bold),
                ])

            # Term Totals Summary Row
            course_table_rows.append([
                Paragraph(
                    f"<b>TERM TOTALS:</b> &nbsp; Attempted: <b>{sem_attempted} CR</b> &nbsp;|&nbsp; Earned: <b>{sem_earned} CR</b> &nbsp;|&nbsp; Quality Points: <b>{term_qp_sum:.2f}</b>",
                    tbl_td_bold
                ),
                "", "", "", "", "",
                Paragraph("<b>TERM GPA:</b>", tbl_td_center_bold),
                Paragraph(f"<b><font color='#064e3b'>{sem_gpa}</font></b>", tbl_td_center_bold),
            ])

            col_widths = [1.0 * inch, 2.7 * inch, 0.55 * inch, 0.55 * inch, 0.65 * inch, 0.6 * inch, 0.65 * inch, 0.9 * inch]
            sem_table = Table(course_table_rows, colWidths=col_widths, repeatRows=1)

            t_styles = [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1e293b")),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("TOPPADDING", (0, 0), (-1, -1), 1.8),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 1.8),
                ("LEFTPADDING", (0, 0), (-1, -1), 4),
                ("RIGHTPADDING", (0, 0), (-1, -1), 4),
                ("GRID", (0, 0), (-1, -2), 0.4, colors.HexColor("#e2e8f0")),
                # Span the Term Totals label across columns 0 to 5
                ("SPAN", (0, -1), (5, -1)),
                ("BACKGROUND", (0, -1), (-1, -1), colors.HexColor("#f1f5f9")),
                ("LINEABOVE", (0, -1), (-1, -1), 1, colors.HexColor("#94a3b8")),
                ("LINEBELOW", (0, -1), (-1, -1), 1, colors.HexColor("#94a3b8")),
            ]

            # Alternate row fills for clean readability
            for i in range(1, len(courses_list) + 1):
                if i % 2 == 0:
                    t_styles.append(("BACKGROUND", (0, i), (-1, i), colors.HexColor("#f8fafc")))

            sem_table.setStyle(TableStyle(t_styles))
            sem_elements.append(sem_table)
            sem_elements.append(Spacer(1, 4.5))
            story.append(KeepTogether(sem_elements))

    # ── 4. Cumulative Academic Performance & Honours Summary ──────────────────
    cum_summary_data = [
        [
            Paragraph("<b>CUMULATIVE ACADEMIC RECORD SUMMARY</b>", ParagraphStyle(
                "CumHead", parent=tbl_th, fontName="Helvetica-Bold", fontSize=8, textColor=colors.white
            )),
            "", "", ""
        ],
        [
            Paragraph(f"<b>Total Credits Attempted:</b> {total_cr_attempted}", lbl_bold),
            Paragraph(f"<b>Total Credits Earned:</b> {total_cr_earned}", lbl_bold),
            Paragraph(f"<b>Cumulative Quality Points:</b> {total_qp}", lbl_bold),
            Paragraph(f"<b>Cumulative GPA (CGPA):</b> <font size=9 color='#064e3b'><b>{cum_gpa}</b></font>", lbl_bold),
        ],
        [
            Paragraph(f"<b>Official Degree / Diploma Classification:</b> &nbsp; <font color='#ca8a04'><b>{classification.upper()}</b></font>", lbl_bold),
            "", "",
            Paragraph("<b>Graduation Status:</b> <font color='#047857'><b>ELIGIBLE / IN PROGRESS</b></font>", lbl_bold),
        ]
    ]
    cum_table = Table(cum_summary_data, colWidths=[2.1 * inch, 1.85 * inch, 1.85 * inch, 1.9 * inch])
    cum_table.setStyle(TableStyle([
        ("SPAN", (0, 0), (-1, 0)),
        ("SPAN", (0, 2), (2, 2)),
        ("BACKGROUND", (0, 0), (-1, 0), c_primary),
        ("BACKGROUND", (0, 1), (-1, -1), colors.HexColor("#fdfdfb")),
        ("BOX", (0, 0), (-1, -1), 1, colors.HexColor("#cbd5e1")),
        ("INNERGRID", (0, 1), (-1, -1), 0.5, colors.HexColor("#e2e8f0")),
        ("TOPPADDING", (0, 0), (-1, -1), 2.2),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2.2),
        ("LEFTPADDING", (0, 0), (-1, -1), 7),
        ("RIGHTPADDING", (0, 0), (-1, -1), 7),
    ]))
    story.append(Spacer(1, 2))
    story.append(KeepTogether([cum_table]))
    story.append(Spacer(1, 4.5))

    # ── 5. Standard Institutional Grading Scale Key ───────────────────────────
    scale_rows = [
        [
            Paragraph("<b>UCC / NMTC 4.0 GRADING SYSTEM & CLASSIFICATION KEY</b>", ParagraphStyle(
                "ScaleHead", fontName="Helvetica-Bold", fontSize=7, leading=9, textColor=c_primary
            )),
            "", "", "", "", "", "", ""
        ],
        [
            Paragraph("<b>A</b> (80-100%)", tbl_td_bold),
            Paragraph("<b>B+</b> (75-79%)", tbl_td_bold),
            Paragraph("<b>B</b> (70-74%)", tbl_td_bold),
            Paragraph("<b>C+</b> (65-69%)", tbl_td_bold),
            Paragraph("<b>C</b> (60-64%)", tbl_td_bold),
            Paragraph("<b>D+</b> (55-59%)", tbl_td_bold),
            Paragraph("<b>D</b> (50-54%)", tbl_td_bold),
            Paragraph("<b>F</b> (&lt;50%)", tbl_td_bold),
        ],
        [
            Paragraph("4.00 · Excellent", tbl_td),
            Paragraph("3.50 · Very Good", tbl_td),
            Paragraph("3.00 · Good", tbl_td),
            Paragraph("2.50 · Fairly Good", tbl_td),
            Paragraph("2.00 · Pass", tbl_td),
            Paragraph("1.50 · Pass", tbl_td),
            Paragraph("1.00 · Pass", tbl_td),
            Paragraph("0.00 · Fail", tbl_td),
        ]
    ]
    scale_table = Table(scale_rows, colWidths=[0.96 * inch] * 8)
    scale_table.setStyle(TableStyle([
        ("SPAN", (0, 0), (-1, 0)),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#f1f5f9")),
        ("BACKGROUND", (0, 1), (-1, -1), colors.HexColor("#fafafa")),
        ("BOX", (0, 0), (-1, -1), 0.6, colors.HexColor("#cbd5e1")),
        ("INNERGRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#e2e8f0")),
        ("ALIGN", (0, 1), (-1, -1), "CENTER"),
        ("TOPPADDING", (0, 0), (-1, -1), 1.6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 1.6),
        ("LEFTPADDING", (0, 0), (-1, -1), 2),
        ("RIGHTPADDING", (0, 0), (-1, -1), 2),
    ]))
    story.append(KeepTogether([scale_table]))
    story.append(Spacer(1, 4.5))

    # ── 6. Official Registrar Authentication & Sign-Off Block ─────────────────
    if is_official:
        sign_data = [
            [
                Paragraph("<b>ACADEMIC AFFAIRS OFFICER</b><br/><br/>___________________________________<br/><b>Registrar / Examinations Officer</b><br/>Signature & Date", ParagraphStyle("SignL", parent=val_norm, alignment=1, fontSize=6.8, leading=8.5)),
                Paragraph(
                    "<font color='#064e3b'><b>S.D.A. NMTC ASAMANG</b></font><br/>"
                    "<font color='#ca8a04'><b>[ OFFICIAL EMBOSSED SEAL ]</b></font><br/>"
                    "Certified Academic Record",
                    ParagraphStyle("SignC", parent=val_norm, alignment=1, fontSize=6.8, leading=8.5)
                ),
                Paragraph("<b>DEAN / HEAD OF INSTITUTION</b><br/><br/>___________________________________<br/><b>Principal / Academic Board</b><br/>Signature & Date", ParagraphStyle("SignR", parent=val_norm, alignment=1, fontSize=6.8, leading=8.5)),
            ]
        ]
        sign_table = Table(sign_data, colWidths=[2.65 * inch, 2.4 * inch, 2.65 * inch])
        sign_table.setStyle(TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#cbd5e1")),
            ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#f8fafc")),
            ("BACKGROUND", (1, 0), (1, 0), colors.HexColor("#f0fdf4")),
            ("LINEBEFORE", (1, 0), (1, -1), 0.5, colors.HexColor("#cbd5e1")),
            ("LINEBEFORE", (2, 0), (2, -1), 0.5, colors.HexColor("#cbd5e1")),
            ("TOPPADDING", (0, 0), (-1, -1), 3),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ("LEFTPADDING", (0, 0), (-1, -1), 8),
            ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ]))
    else:
        arrears_txt = f"due to fee arrears of GH¢ {float(hold_info['amount_due']):,.2f}" if hold_info and hold_info.get('amount_due') else "for student advising only"
        sign_data = [
            [
                Paragraph(
                    "<b>UNOFFICIAL ACADEMIC RECORD • STUDENT ADVISORY COPY</b><br/>"
                    f"This document is issued {arrears_txt}. "
                    "It does not bear the official signature of the Registrar or the embossed seal of the College. "
                    "This record is invalid for transfer of credit, employment verification, or credential assessment. "
                    "To obtain an Official Academic Transcript, students must resolve any outstanding fee arrears through Student Financials.",
                    ParagraphStyle("UnofficialNotice", parent=val_norm, alignment=1, fontSize=6.8, leading=8.5, textColor=colors.HexColor("#92400e"))
                )
            ]
        ]
        sign_table = Table(sign_data, colWidths=[7.7 * inch])
        sign_table.setStyle(TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("BOX", (0, 0), (-1, -1), 0.8, colors.HexColor("#f59e0b")),
            ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#fffbeb")),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ("LEFTPADDING", (0, 0), (-1, -1), 10),
            ("RIGHTPADDING", (0, 0), (-1, -1), 10),
        ]))
    story.append(KeepTogether([sign_table]))

    # Build the PDF using our custom security canvas with dynamic official/unofficial state
    class ConfiguredCanvas(TranscriptCanvas):
        pass

    ConfiguredCanvas.is_official = is_official
    ConfiguredCanvas.hold_info = hold_info

    doc.build(story, canvasmaker=ConfiguredCanvas)
    buffer.seek(0)
    return buffer

