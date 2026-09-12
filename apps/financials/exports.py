"""
CSV and data export utilities for Student Financials (Ghana Cedis GH₵).
Role-tailored for Finance Officers, Bursars, and Students.
"""
import csv
from decimal import Decimal
from django.http import HttpResponse
from django.utils import timezone
from .models import StudentAccountStatement, Payment, FinancialHold


def export_student_statements_csv(semester=None, academic_level=None, status_filter=None):
    """
    Generate CSV of student account statements for the Finance Directorate.
    Includes breakdown of fees, payments, balances in GH₵, and registration hold status.
    """
    qs = (
        StudentAccountStatement.objects
        .all()
        .select_related("student")
        .order_by("academic_level", "student__last_name", "student__first_name")
    )
    if semester:
        qs = qs.filter(semester=semester)
    if academic_level and academic_level != "all":
        qs = qs.filter(academic_level=academic_level)
    if status_filter and status_filter != "all":
        qs = qs.filter(status=status_filter)

    active_holds = set(FinancialHold.objects.filter(is_active=True).values_list("student_id", flat=True))

    timestamp_str = timezone.now().strftime("%Y%m%d_%H%M")
    filename = f"student_financial_statements_{academic_level or 'all'}_{timestamp_str}.csv"

    response = HttpResponse(content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    response.write("\ufeff")  # UTF-8 BOM for Microsoft Excel compatibility

    writer = csv.writer(response)
    writer.writerow([
        "Student ID / Index No",
        "Student Full Name",
        "Email Address",
        "Academic Level",
        "Semester",
        "Academic Tuition (GH₵)",
        "ICT & Library (GH₵)",
        "SRC Dues (GH₵)",
        "Examination Fee (GH₵)",
        "Bursary / Scholarship (GH₵)",
        "Total Billed (GH₵)",
        "Total Paid (GH₵)",
        "Outstanding Balance / Arrears (GH₵)",
        "Payment Status",
        "Registration Hold Active",
        "Due Date",
    ])

    for stmt in qs:
        student = stmt.student
        index_num = getattr(student, "student_id", "") or f"UG-{str(student.id)[:8].upper()}"
        has_hold = "YES (Blocked)" if student.id in active_holds else "NO (Clear)"

        writer.writerow([
            index_num,
            student.full_name or student.email,
            student.email,
            f"Level {stmt.academic_level}",
            stmt.semester,
            f"{stmt.academic_fee:.2f}",
            f"{stmt.ict_library_fee:.2f}",
            f"{stmt.src_dues:.2f}",
            f"{stmt.examination_fee:.2f}",
            f"{stmt.bursary_aid:.2f}",
            f"{stmt.total_billed:.2f}",
            f"{stmt.total_paid:.2f}",
            f"{stmt.balance:.2f}",
            stmt.get_status_display(),
            has_hold,
            stmt.due_date.strftime("%Y-%m-%d") if stmt.due_date else "N/A",
        ])

    return response


def export_payments_ledger_csv(channel=None, status_filter=None):
    """
    Generate CSV of university revenue inflows and payments ledger.
    Captures Mobile Money and Direct Bank Sync transactions.
    """
    qs = (
        Payment.objects
        .all()
        .select_related("student", "statement")
        .order_by("-created_at")
    )
    if channel and channel != "all":
        qs = qs.filter(channel=channel)
    if status_filter and status_filter != "all":
        qs = qs.filter(status=status_filter)

    timestamp_str = timezone.now().strftime("%Y%m%d_%H%M")
    filename = f"revenue_payments_ledger_{channel or 'all'}_{timestamp_str}.csv"

    response = HttpResponse(content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    response.write("\ufeff")

    writer = csv.writer(response)
    writer.writerow([
        "Receipt Number",
        "Transaction Reference",
        "Student ID / Index No",
        "Student Full Name",
        "Student Email",
        "Amount (GH₵)",
        "Payment Channel",
        "Provider / Bank",
        "Account / Phone / Teller",
        "Payment Status",
        "Payment Date & Time",
        "Verification / Approval Date",
        "Transaction Notes",
    ])

    for p in qs:
        student = p.student
        index_num = getattr(student, "student_id", "") or f"UG-{str(student.id)[:8].upper()}" if student else "N/A"
        student_name = student.full_name if student else "N/A"
        student_email = student.email if student else "N/A"

        writer.writerow([
            p.receipt_number or f"RCP-{p.id}",
            p.reference_number,
            index_num,
            student_name,
            student_email,
            f"{p.amount:.2f}",
            p.get_channel_display(),
            p.provider or "N/A",
            p.phone_or_account or "N/A",
            p.get_status_display(),
            p.created_at.strftime("%Y-%m-%d %H:%M:%S") if p.created_at else "",
            p.verified_at.strftime("%Y-%m-%d %H:%M:%S") if p.verified_at else "N/A",
            p.notes,
        ])

    return response


def export_student_personal_statement_csv(student):
    """
    Generate student's personal semester billing and payment ledger CSV.
    """
    stmt = (
        StudentAccountStatement.objects
        .filter(student=student)
        .order_by("-created_at")
        .first()
    )

    payments = (
        Payment.objects
        .filter(student=student)
        .order_by("-created_at")
    )

    index_num = getattr(student, "student_id", "") or f"UG-{str(student.id)[:8].upper()}"
    filename = f"student_financial_statement_{index_num}.csv"

    response = HttpResponse(content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    response.write("\ufeff")

    writer = csv.writer(response)
    writer.writerow(["OFFICIAL STUDENT STATEMENT OF ACCOUNT (GHANA CEDIS - GH₵)"])
    writer.writerow(["Student Name", student.full_name or student.email])
    writer.writerow(["Student ID / Index No", index_num])
    writer.writerow(["Email Address", student.email])
    writer.writerow(["Exported Date", timezone.now().strftime("%Y-%m-%d %H:%M:%S")])
    writer.writerow([])

    if stmt:
        writer.writerow(["SEMESTER BILLING BREAKDOWN", stmt.semester])
        writer.writerow(["Line Item", "Amount (GH₵)"])
        writer.writerow(["Academic Facility & Tuition Fee", f"{stmt.academic_fee:.2f}"])
        writer.writerow(["ICT & Digital Library Levy", f"{stmt.ict_library_fee:.2f}"])
        writer.writerow(["SRC Student Dues", f"{stmt.src_dues:.2f}"])
        writer.writerow(["Examination & Moderation Levy", f"{stmt.examination_fee:.2f}"])
        if stmt.bursary_aid > Decimal("0.00"):
            writer.writerow(["Less: Institutional Bursary / Aid", f"-{stmt.bursary_aid:.2f}"])
        writer.writerow(["TOTAL SEMESTER TARIFF BILLED", f"{stmt.total_billed:.2f}"])
        writer.writerow(["TOTAL PAYMENTS CREDITED", f"{stmt.total_paid:.2f}"])
        writer.writerow(["OUTSTANDING BALANCE / ARREARS", f"{stmt.balance:.2f}"])
        writer.writerow(["ACCOUNT STATUS", stmt.get_status_display()])
        writer.writerow([])

    writer.writerow(["PAYMENT TRANSACTION HISTORY"])
    writer.writerow(["Receipt Number", "Date & Time", "Channel", "Provider", "Reference", "Amount (GH₵)", "Status"])
    for p in payments:
        writer.writerow([
            p.receipt_number,
            p.created_at.strftime("%Y-%m-%d %H:%M") if p.created_at else "",
            p.get_channel_display(),
            p.provider,
            p.reference_number,
            f"{p.amount:.2f}",
            p.get_status_display(),
        ])

    return response
