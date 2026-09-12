"""Official University Payment Receipt Generator using ReportLab (Ghana Cedis GH₵)."""
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
from .models import Payment


class ReceiptWatermarkedCanvas(canvas.Canvas):
    """Custom canvas to draw an official PAID watermark stamp and footer."""
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

        # Watermark "OFFICIAL RECEIPT - PAID"
        self.saveState()
        self.setFont("Helvetica-Bold", 45)
        self.setFillColor(colors.HexColor("#0f172a"), alpha=0.04)
        self.translate(w / 2, h / 2)
        self.rotate(35)
        self.drawCentredString(0, 0, "OFFICIAL RECEIPT · PAID")
        self.restoreState()

        # Footer
        self.setFont("Helvetica", 8)
        self.setFillColor(colors.HexColor("#64748b"))
        self.drawString(0.75 * inch, 0.45 * inch, "UniPortal Accounts Directorate — Generated Official Financial Record")
        page_str = f"Page {self._pageNumber} of {total_pages}"
        self.drawRightString(w - 0.75 * inch, 0.45 * inch, page_str)

        self.restoreState()


class PaymentReceiptGenerator:
    def __init__(self, payment: Payment):
        self.payment = payment
        self.student = payment.student
        self.statement = payment.statement
        self.styles = getSampleStyleSheet()
        self._init_styles()

    def _init_styles(self):
        self.styles.add(ParagraphStyle(
            "UniHeader",
            fontName="Helvetica-Bold",
            fontSize=16,
            leading=20,
            textColor=colors.HexColor("#1e1b4b"),
            alignment=1,
        ))
        self.styles.add(ParagraphStyle(
            "UniSubheader",
            fontName="Helvetica-Bold",
            fontSize=10,
            leading=13,
            textColor=colors.HexColor("#4338ca"),
            alignment=1,
        ))
        self.styles.add(ParagraphStyle(
            "ReceiptTitle",
            fontName="Helvetica-Bold",
            fontSize=13,
            leading=16,
            textColor=colors.HexColor("#0f172a"),
            alignment=1,
        ))
        self.styles.add(ParagraphStyle(
            "FieldLabel",
            fontName="Helvetica-Bold",
            fontSize=8.5,
            leading=11,
            textColor=colors.HexColor("#475569"),
        ))
        self.styles.add(ParagraphStyle(
            "FieldValue",
            fontName="Helvetica",
            fontSize=9,
            leading=12,
            textColor=colors.HexColor("#0f172a"),
        ))
        self.styles.add(ParagraphStyle(
            "AmountPaidBig",
            fontName="Helvetica-Bold",
            fontSize=18,
            leading=22,
            textColor=colors.HexColor("#047857"),
            alignment=1,
        ))
        self.styles.add(ParagraphStyle(
            "StampText",
            fontName="Helvetica-Bold",
            fontSize=8,
            leading=10,
            textColor=colors.HexColor("#065f46"),
            alignment=1,
        ))

    def generate(self) -> bytes:
        buffer = io.BytesIO()
        doc = SimpleDocTemplate(
            buffer,
            pagesize=letter,
            leftMargin=0.75 * inch,
            rightMargin=0.75 * inch,
            topMargin=0.75 * inch,
            bottomMargin=0.75 * inch,
        )

        story = []

        # ── Header ──────────────────────────────────────────────────────────
        story.append(Paragraph("UNIPORTAL UNIVERSITY · GHANA", self.styles["UniHeader"]))
        story.append(Paragraph("DIRECTORATE OF FINANCE & STUDENT ACCOUNTS", self.styles["UniSubheader"]))
        story.append(Spacer(1, 4))
        story.append(Paragraph("OFFICIAL STUDENT FEE PAYMENT RECEIPT", self.styles["ReceiptTitle"]))
        story.append(Spacer(1, 8))
        story.append(HRFlowable(width="100%", thickness=1.5, color=colors.HexColor("#4338ca"), spaceAfter=14))

        # ── Receipt & Student Details Box ────────────────────────────────────
        student_id_str = getattr(self.student, "student_id", None) or f"UG-{str(self.student.id)[:8].upper()}"
        student_name = f"{self.student.first_name} {self.student.last_name}".strip() or self.student.email

        details_data = [
            [
                Paragraph("<b>Receipt Number:</b>", self.styles["FieldLabel"]),
                Paragraph(f"<b>{self.payment.receipt_number}</b>", self.styles["FieldValue"]),
                Paragraph("<b>Date & Time:</b>", self.styles["FieldLabel"]),
                Paragraph(self.payment.created_at.strftime("%b %d, %Y at %H:%M GMT"), self.styles["FieldValue"]),
            ],
            [
                Paragraph("<b>Student Name:</b>", self.styles["FieldLabel"]),
                Paragraph(student_name, self.styles["FieldValue"]),
                Paragraph("<b>Student ID / Index:</b>", self.styles["FieldLabel"]),
                Paragraph(f"<b>{student_id_str}</b>", self.styles["FieldValue"]),
            ],
            [
                Paragraph("<b>Academic Semester:</b>", self.styles["FieldLabel"]),
                Paragraph(self.statement.semester, self.styles["FieldValue"]),
                Paragraph("<b>Department:</b>", self.styles["FieldLabel"]),
                Paragraph(getattr(self.student, "department", "Computer Science") or "General Studies", self.styles["FieldValue"]),
            ],
            [
                Paragraph("<b>Payment Channel:</b>", self.styles["FieldLabel"]),
                Paragraph(f"{self.payment.get_channel_display()} ({self.payment.provider})", self.styles["FieldValue"]),
                Paragraph("<b>Transaction Ref:</b>", self.styles["FieldLabel"]),
                Paragraph(f"<code>{self.payment.reference_number}</code>", self.styles["FieldValue"]),
            ]
        ]

        details_table = Table(details_data, colWidths=[1.4 * inch, 2.1 * inch, 1.4 * inch, 2.1 * inch])
        details_table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#f8fafc")),
            ("BOX", (0, 0), (-1, -1), 1, colors.HexColor("#cbd5e1")),
            ("INNERGRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#e2e8f0")),
            ("TOPPADDING", (0, 0), (-1, -1), 6),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ("LEFTPADDING", (0, 0), (-1, -1), 8),
            ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ]))
        story.append(details_table)
        story.append(Spacer(1, 16))

        # ── Amount Paid Banner ──────────────────────────────────────────────
        banner_data = [
            [
                Paragraph("AMOUNT RECEIVED (GHANA CEDIS)", ParagraphStyle("BannerSub", fontName="Helvetica-Bold", fontSize=9, textColor=colors.HexColor("#065f46"), alignment=1)),
            ],
            [
                Paragraph(f"GH₵ {self.payment.amount:,.2f}", self.styles["AmountPaidBig"]),
            ],
            [
                Paragraph(f"Status: <b>{self.payment.get_status_display().upper()}</b> · Reference: {self.payment.reference_number}", ParagraphStyle("BannerNotes", fontName="Helvetica", fontSize=8.5, textColor=colors.HexColor("#047857"), alignment=1))
            ]
        ]
        banner_table = Table(banner_data, colWidths=[7.0 * inch])
        banner_table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#ecfdf5")),
            ("BOX", (0, 0), (-1, -1), 1.5, colors.HexColor("#10b981")),
            ("TOPPADDING", (0, 0), (-1, -1), 8),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
        ]))
        story.append(banner_table)
        story.append(Spacer(1, 18))

        # ── Fee Account Ledger Breakdown ────────────────────────────────────
        story.append(Paragraph("<b>Semester Account Ledger Summary</b>", ParagraphStyle("LedgerHead", fontName="Helvetica-Bold", fontSize=10.5, textColor=colors.HexColor("#1e293b"))))
        story.append(Spacer(1, 6))

        ledger_data = [
            [
                Paragraph("<b>Fee Item Description</b>", self.styles["FieldLabel"]),
                Paragraph("<b>Semester Bill (GH₵)</b>", self.styles["FieldLabel"]),
            ],
            [
                Paragraph("Academic Facility User Fee & Tuition", self.styles["FieldValue"]),
                Paragraph(f"GH₵ {self.statement.academic_fee:,.2f}", self.styles["FieldValue"]),
            ],
            [
                Paragraph("ICT & Digital Library User Fee", self.styles["FieldValue"]),
                Paragraph(f"GH₵ {self.statement.ict_library_fee:,.2f}", self.styles["FieldValue"]),
            ],
            [
                Paragraph("Examination & Assessment Fee", self.styles["FieldValue"]),
                Paragraph(f"GH₵ {self.statement.examination_fee:,.2f}", self.styles["FieldValue"]),
            ],
            [
                Paragraph("SRC Dues & Student Levies", self.styles["FieldValue"]),
                Paragraph(f"GH₵ {self.statement.src_dues:,.2f}", self.styles["FieldValue"]),
            ],
        ]

        if self.statement.bursary_aid > Decimal("0.00"):
            ledger_data.append([
                Paragraph("<i>Less: Approved Institutional Bursary / Scholarship</i>", self.styles["FieldValue"]),
                Paragraph(f"- GH₵ {self.statement.bursary_aid:,.2f}", ParagraphStyle("BursaryTxt", fontName="Helvetica-Bold", fontSize=9, textColor=colors.HexColor("#059669"))),
            ])

        ledger_data.extend([
            [
                Paragraph("<b>Total Semester Bill Billed</b>", self.styles["FieldLabel"]),
                Paragraph(f"<b>GH₵ {self.statement.total_billed:,.2f}</b>", self.styles["FieldValue"]),
            ],
            [
                Paragraph("<b>Total Payments Credited to Date</b>", self.styles["FieldLabel"]),
                Paragraph(f"<b>GH₵ {self.statement.total_paid:,.2f}</b>", ParagraphStyle("PaidAmt", fontName="Helvetica-Bold", fontSize=9, textColor=colors.HexColor("#047857"))),
            ],
            [
                Paragraph("<b>Current Outstanding Balance</b>", self.styles["FieldLabel"]),
                Paragraph(
                    f"<b>GH₵ {self.statement.balance:,.2f}</b> ({self.statement.get_status_display()})",
                    ParagraphStyle(
                        "BalAmt",
                        fontName="Helvetica-Bold",
                        fontSize=9.5,
                        textColor=colors.HexColor("#dc2626") if self.statement.balance > Decimal("0.00") else colors.HexColor("#047857")
                    )
                ),
            ]
        ])

        ledger_table = Table(ledger_data, colWidths=[4.8 * inch, 2.2 * inch])
        ledger_table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#f1f5f9")),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#e2e8f0")),
            ("TOPPADDING", (0, 0), (-1, -1), 5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ("LINEBELOW", (0, -3), (-1, -3), 1, colors.HexColor("#94a3b8")),
            ("BACKGROUND", (0, -3), (-1, -1), colors.HexColor("#f8fafc")),
        ]))
        story.append(ledger_table)
        story.append(Spacer(1, 24))

        # ── Official University Digital Stamp & Clearance Notice ───────────
        stamp_box_data = [
            [
                Paragraph(
                    "<b>OFFICIAL FINANCE ENDORSEMENT</b><br/>"
                    "This electronic payment receipt is an authentic University financial document.<br/>"
                    "Valid for Semester Course Registration, Hall Residency & Examination Clearance.<br/>"
                    f"<i>Issued under authority of the Directorate of Finance · {timezone.now().strftime('%Y-%m-%d')}</i>",
                    ParagraphStyle("NoticeTxt", fontName="Helvetica", fontSize=8, leading=11, textColor=colors.HexColor("#334155"))
                ),
                Paragraph(
                    "★ UNIPORTAL GHANA ★<br/>"
                    "<b>ACCOUNTS CERTIFIED</b><br/>"
                    f"<b>{self.payment.receipt_number}</b><br/>"
                    "DIGITALLY VERIFIED",
                    ParagraphStyle("StampBoxTxt", fontName="Helvetica-Bold", fontSize=8, leading=11, alignment=1, textColor=colors.HexColor("#065f46"))
                )
            ]
        ]
        stamp_table = Table(stamp_box_data, colWidths=[4.9 * inch, 2.1 * inch])
        stamp_table.setStyle(TableStyle([
            ("BOX", (0, 0), (-1, -1), 1, colors.HexColor("#cbd5e1")),
            ("BACKGROUND", (0, 0), (0, 0), colors.HexColor("#f8fafc")),
            ("BACKGROUND", (1, 0), (1, 0), colors.HexColor("#ecfdf5")),
            ("BOX", (1, 0), (1, 0), 1.5, colors.HexColor("#059669")),
            ("TOPPADDING", (0, 0), (-1, -1), 8),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
            ("LEFTPADDING", (0, 0), (-1, -1), 10),
            ("RIGHTPADDING", (0, 0), (-1, -1), 10),
        ]))
        story.append(stamp_table)

        doc.build(story, canvasmaker=ReceiptWatermarkedCanvas)
        return buffer.getvalue()
