"""
Roster Ingestion Service.
Parses, validates, and provisions student cohorts from Ministry of Health (MOH)
admissions lists with automated ASDAM Student ID generation.
Supports both CSV and Excel (.xlsx) formats with tolerant header recognition.
"""
import io
import csv
import re
import secrets
import logging
import threading
from typing import Dict, Any, List, Optional, Tuple
from django.db import transaction
from django.utils import timezone
from apps.users.models import User, UserProfile
from .id_generator import (
    generate_asdam_student_id,
    normalize_program,
    normalize_class_name,
    normalize_year,
)

logger = logging.getLogger(__name__)

HEADER_MAP: Dict[str, str] = {
    # MOH PIN / Index variations
    "moh_pin": "moh_pin",
    "pin": "moh_pin",
    "moh pin": "moh_pin",
    "pin_no": "moh_pin",
    "pin no": "moh_pin",
    "pin_number": "moh_pin",
    "pin number": "moh_pin",
    "moh_index": "moh_pin",
    "moh index": "moh_pin",
    "index": "moh_pin",
    "index_number": "moh_pin",
    "index number": "moh_pin",
    "index_no": "moh_pin",
    "index no": "moh_pin",
    "applicant_id": "moh_pin",
    "applicant id": "moh_pin",
    "application_number": "moh_pin",
    "application number": "moh_pin",
    "application_no": "moh_pin",
    "application no": "moh_pin",
    "app_no": "moh_pin",
    "app no": "moh_pin",
    "app_number": "moh_pin",
    "app number": "moh_pin",
    "admission_number": "moh_pin",
    "admission number": "moh_pin",
    "admission_no": "moh_pin",
    "admission no": "moh_pin",
    "adm_no": "moh_pin",
    "adm no": "moh_pin",
    "matric_number": "moh_pin",
    "matric number": "moh_pin",
    "matric_no": "moh_pin",
    "matric no": "moh_pin",
    "wassce_index": "moh_pin",
    "wassce index": "moh_pin",
    "wassce_index_number": "moh_pin",
    "wassce index number": "moh_pin",
    "wassce_index_no": "moh_pin",
    "wassce index no": "moh_pin",
    "reference_number": "moh_pin",
    "reference number": "moh_pin",
    "reference_no": "moh_pin",
    "reference no": "moh_pin",
    "ref_no": "moh_pin",
    "ref no": "moh_pin",
    "form_number": "moh_pin",
    "form number": "moh_pin",
    "form_no": "moh_pin",
    "form no": "moh_pin",
    "reg_number": "moh_pin",
    "reg number": "moh_pin",
    "reg_no": "moh_pin",
    "reg no": "moh_pin",
    "student_id": "moh_pin",
    "student id": "moh_pin",
    "id_number": "moh_pin",
    "id number": "moh_pin",
    "candidate_id": "moh_pin",
    "candidate id": "moh_pin",

    # Serial Number variations
    "serial_number": "serial_number",
    "serial number": "serial_number",
    "serial": "serial_number",
    "serial_no": "serial_number",
    "serial no": "serial_number",
    "serial_num": "serial_number",
    "serial num": "serial_number",
    "voucher": "serial_number",
    "voucher_serial": "serial_number",
    "voucher serial": "serial_number",
    "voucher_code": "serial_number",
    "voucher code": "serial_number",
    "voucher_pin": "serial_number",
    "voucher pin": "serial_number",
    "voucher_number": "serial_number",
    "voucher number": "serial_number",
    "passcode": "serial_number",
    "password": "serial_number",
    "secret": "serial_number",
    "token": "serial_number",

    # First Name
    "first_name": "first_name",
    "first name": "first_name",
    "firstname": "first_name",
    "first_names": "first_name",
    "first names": "first_name",
    "firstnames": "first_name",
    "given_name": "first_name",
    "given name": "first_name",
    "given_names": "first_name",
    "given names": "first_name",
    "other_name": "first_name",
    "other name": "first_name",
    "other_names": "first_name",
    "other names": "first_name",
    "othernames": "first_name",

    # Last Name / Surname
    "last_name": "last_name",
    "last name": "last_name",
    "lastname": "last_name",
    "surname": "last_name",
    "surnames": "last_name",
    "family_name": "last_name",
    "family name": "last_name",

    # Full Name
    "name": "full_name",
    "names": "full_name",
    "full_name": "full_name",
    "full name": "full_name",
    "fullname": "full_name",
    "student_name": "full_name",
    "student name": "full_name",
    "candidate_name": "full_name",
    "candidate name": "full_name",
    "applicant_name": "full_name",
    "applicant name": "full_name",

    # Program / Department
    "program": "program",
    "programme": "program",
    "department": "program",
    "course": "program",
    "major": "program",
    "study_program": "program",
    "study program": "program",
    "discipline": "program",

    # Class / Level
    "class": "class_name",
    "class_name": "class_name",
    "class name": "class_name",
    "level": "class_name",
    "academic_level": "class_name",
    "academic level": "class_name",
    "class_level": "class_name",
    "class level": "class_name",

    # Year
    "year": "admission_year",
    "admission_year": "admission_year",
    "admission year": "admission_year",
    "enrollment_year": "admission_year",
    "enrollment year": "admission_year",
    "academic_year": "admission_year",
    "academic year": "admission_year",
    "entry_year": "admission_year",
    "entry year": "admission_year",
    "cohort": "admission_year",

    # Contact
    "phone": "phone",
    "phone_number": "phone",
    "phone number": "phone",
    "phone_no": "phone",
    "phone no": "phone",
    "mobile": "phone",
    "mobile_number": "phone",
    "mobile number": "phone",
    "mobile_no": "phone",
    "mobile no": "phone",
    "telephone": "phone",
    "tel": "phone",
    "contact": "phone",
    "contact_number": "phone",
    "contact number": "phone",
    "whatsapp": "phone",
    "email": "email",
    "email_address": "email",
    "email address": "email",
    "mail": "email",
}


HEADER_KEYWORDS = {
    "pin", "index", "id", "applicant", "application", "reference", "ref", "form", "reg", "roll",
    "name", "first", "last", "surname", "candidate", "student", "matric", "admission",
    "program", "programme", "course", "department", "major",
    "class", "level", "year", "phone", "mobile", "tel", "contact", "email", "serial", "voucher",
    "gender", "sex", "aggregate", "score", "status", "sn", "s/n", "no"
}


def is_banner_text(text: str) -> bool:
    """Detect if cell text looks like an institutional banner, document title or header note."""
    t = str(text or "").strip().lower()
    if len(t) > 35:
        return True
    return any(w in t for w in ("list", "college", "ministry", "training", "admissions", "school", "portal", "ghana"))


def clean_header_str(h: Any) -> str:
    """Strip special characters and normalize header label."""
    raw = str(h or "").strip().lower()
    # Replace dashes, dots, underscores, colons with space
    cleaned = re.sub(r'[^a-z0-9]+', ' ', raw).strip()
    return cleaned


def score_header_row(row: List[Any]) -> int:
    """Calculate likelihood that a row is the primary table column header row."""
    cells = [str(c or "").strip() for c in row if c is not None and str(c).strip()]
    if len(cells) < 2:
        return -1
    if any(is_banner_text(c) for c in cells):
        return -1
    score = 0
    for c in cells:
        clean = clean_header_str(c)
        words = clean.split()
        if any(w in HEADER_KEYWORDS for w in words):
            score += 2
        if clean in HEADER_MAP:
            score += 3
    return score


def find_header_and_data_rows(all_raw_rows: List[List[str]]) -> Tuple[List[str], List[List[str]]]:
    """Find the best column header row and return (headers, data_rows)."""
    if not all_raw_rows:
        return [], []
    if len(all_raw_rows) == 1:
        return all_raw_rows[0], []

    best_idx = 0
    best_score = -1
    search_limit = min(15, len(all_raw_rows))

    for idx in range(search_limit):
        score = score_header_row(all_raw_rows[idx])
        if score > best_score:
            best_score = score
            best_idx = idx

    if best_score <= 0:
        non_empty_0 = len([c for c in all_raw_rows[0] if c.strip()])
        non_empty_1 = len([c for c in all_raw_rows[1] if c.strip()]) if len(all_raw_rows) > 1 else 0
        best_idx = 1 if non_empty_1 > non_empty_0 and non_empty_0 <= 2 else 0

    return all_raw_rows[best_idx], all_raw_rows[best_idx + 1:]


def normalize_headers(raw_headers: List[Any]) -> Dict[str, str]:
    """Map raw CSV / Excel header keys to standardized internal keys with fuzzy heuristics."""
    mapping: Dict[str, str] = {}
    used_targets = set()

    for h in raw_headers:
        if not h:
            continue
        original = str(h).strip()
        if is_banner_text(original):
            continue
        cleaned = clean_header_str(original)
        compressed = cleaned.replace(" ", "")

        # 1. Direct dictionary match
        target = HEADER_MAP.get(cleaned) or HEADER_MAP.get(cleaned.replace(" ", "_"))
        if not target:
            # 2. Compressed match
            for k, v in HEADER_MAP.items():
                if k.replace(" ", "").replace("_", "") == compressed:
                    target = v
                    break

        # 3. Fuzzy heuristics if not matched yet
        if not target:
            if any(term in cleaned for term in ("full name", "student name", "candidate name", "applicant name", "name of applicant", "name of candidate")):
                target = "full_name"
            elif any(term in cleaned for term in ("moh", "pin", "index", "matric", "admission no", "adm no", "app no", "ref no", "reference no")):
                target = "moh_pin"
            elif any(term in cleaned for term in ("serial", "voucher")):
                target = "serial_number"
            elif any(term in cleaned for term in ("surname", "last name", "family name")):
                target = "last_name"
            elif any(term in cleaned for term in ("first name", "given name", "other name")):
                target = "first_name"
            elif cleaned == "name" or cleaned == "names":
                target = "full_name"
            elif any(term in cleaned for term in ("program", "programme", "course", "department", "major")):
                target = "program"
            elif any(term in cleaned for term in ("level", "class", "academic level")):
                target = "class_name"
            elif any(term in cleaned for term in ("phone", "mobile", "contact", "tel", "whatsapp")):
                target = "phone"
            elif any(term in cleaned for term in ("email", "mail")):
                target = "email"

        if target and target not in used_targets:
            mapping[original] = target
            used_targets.add(target)

    return mapping


def generate_sample_csv_template() -> str:
    """Generate sample CSV template with example records for Nursing and Midwifery."""
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "first_name", "last_name", "moh_pin", "serial_number",
        "program", "class", "year", "phone", "email"
    ])
    writer.writerow([
        "Abena", "Osei", "MOH-NUR-2026-001", "SN-882194",
        "Nursing", "Level 100", "2026", "0241234567", "abena.osei@example.com"
    ])
    writer.writerow([
        "Grace", "Mensah", "MOH-MID-2026-002", "SN-882195",
        "Midwifery", "Level 100", "2026", "0247654321", "grace.mensah@example.com"
    ])
    return output.getvalue()


def extract_rows_from_file(csv_file) -> Tuple[List[str], List[List[str]]]:
    """
    Extract raw headers and rows from either CSV, TSV, or Excel (.xlsx) file.
    """
    if hasattr(csv_file, "read"):
        content = csv_file.read()
    elif isinstance(csv_file, bytes):
        content = csv_file
    elif isinstance(csv_file, str):
        content = csv_file.encode("utf-8")
    else:
        raise ValueError("Invalid file object provided.")

    if not content:
        return [], []

    # Check for Excel ZIP header (PK\x03\x04)
    if content.startswith(b"PK\x03\x04"):
        try:
            import openpyxl
            wb = openpyxl.load_workbook(io.BytesIO(content), data_only=True)
            sheet = wb.active
            all_raw_rows = []
            for r in sheet.iter_rows(values_only=True):
                if r and any(c is not None and str(c).strip() for c in r):
                    all_raw_rows.append([str(c if c is not None else "").strip() for c in r])
            return find_header_and_data_rows(all_raw_rows)
        except Exception as e:
            logger.warning("Failed parsing as Excel file, falling back to CSV: %s", e)

    # Decode CSV/TSV handling UTF-8-sig, Latin-1, or Windows-1252
    text = ""
    for enc in ("utf-8-sig", "utf-8", "latin-1", "cp1252"):
        try:
            text = content.decode(enc)
            break
        except UnicodeDecodeError:
            continue

    if not text:
        text = content.decode("utf-8", errors="replace")

    text = text.strip()
    if not text:
        return [], []

    # Detect delimiter
    sample = text[:4096]
    delimiter = ","
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",\t;|")
        delimiter = dialect.delimiter
    except Exception:
        delimiter = ","

    reader = csv.reader(io.StringIO(text), delimiter=delimiter)
    all_raw_rows = [row for row in reader if row and any(str(c).strip() for c in row)]

    return find_header_and_data_rows(all_raw_rows)


def process_roster_csv(
    csv_file,
    default_program: Optional[str] = None,
    default_class: str = "100",
    default_year: Optional[int] = None,
    dry_run: bool = False,
    uploader: Optional[User] = None,
) -> Dict[str, Any]:
    """
    Parse, validate, and import an MOH student roster CSV or Excel file.
    Operates inside an atomic transaction.
    """
    try:
        raw_headers, data_rows = extract_rows_from_file(csv_file)
    except Exception as e:
        return {
            "success": False,
            "total_rows": 0,
            "imported_count": 0,
            "skipped_count": 0,
            "students": [],
            "errors": [{"row": 0, "error": f"Failed reading file format: {str(e)}"}],
        }

    if not raw_headers:
        return {
            "success": False,
            "total_rows": 0,
            "imported_count": 0,
            "skipped_count": 0,
            "students": [],
            "errors": [{"row": 0, "error": "The uploaded file is empty or missing headers."}],
        }

    header_map = normalize_headers(raw_headers)
    mapped_targets = set(header_map.values())

    # We require either student names or an identifier column
    has_identifier = "moh_pin" in mapped_targets
    has_name = any(k in mapped_targets for k in ("first_name", "last_name", "full_name"))

    if not has_identifier and not has_name:
        detected_labels = [h for h in raw_headers if h.strip()]
        return {
            "success": False,
            "total_rows": 0,
            "imported_count": 0,
            "skipped_count": 0,
            "students": [],
            "errors": [
                {
                    "row": 1,
                    "error": (
                        "Could not detect student names or identifiers in the uploaded roster. "
                        f"Detected columns: {detected_labels[:8]}"
                    ),
                }
            ],
        }

    has_serial_column = "serial_number" in mapped_targets

    rows_to_process = []
    for row_idx, raw_row in enumerate(data_rows, start=2):
        if not any(str(c or "").strip() for c in raw_row):
            continue

        row_dict: Dict[str, str] = {}
        for col_idx, val in enumerate(raw_row):
            if col_idx < len(raw_headers):
                raw_h = raw_headers[col_idx]
                target_k = header_map.get(raw_h)
                if target_k:
                    row_dict[target_k] = str(val or "").strip()

        if not any(row_dict.values()):
            continue
        combined_text = " ".join(row_dict.values()).lower()
        if any(f in combined_text for f in ("total count", "grand total", "total students", "page 1", "page 2", "approved by", "signature:")):
            continue

        rows_to_process.append((row_idx, row_dict))

    if not rows_to_process:
        return {
            "success": False,
            "total_rows": 0,
            "imported_count": 0,
            "skipped_count": 0,
            "students": [],
            "errors": [{"row": 0, "error": "No student records found below the header row."}],
        }

    imported_students: List[Dict[str, Any]] = []
    errors: List[Dict[str, Any]] = []
    seen_pins_in_batch = set()

    # Pre-load existing MOH PINs and emails to avoid N+1 queries
    existing_pins = set(
        User.objects.exclude(moh_pin__isnull=True).exclude(moh_pin="").values_list("moh_pin", flat=True)
    )
    existing_emails = set(User.objects.values_list("email", flat=True))

    with transaction.atomic():
        for row_num, row in rows_to_process:
            first_name = row.get("first_name", "").strip()
            last_name = row.get("last_name", "").strip()
            full_name = row.get("full_name", "").strip()
            moh_pin = row.get("moh_pin", "").strip().upper()
            serial_number = row.get("serial_number", "").strip()

            # Skip empty or non-student rows
            if not (first_name or last_name or full_name or moh_pin):
                continue

            # Name extraction
            if not first_name or not last_name:
                if full_name:
                    parts = full_name.split()
                    first_name = parts[0]
                    last_name = " ".join(parts[1:]) if len(parts) > 1 else "Student"
                elif first_name and not last_name:
                    last_name = "Student"
                elif last_name and not first_name:
                    first_name = "Student"
                else:
                    errors.append({"row": row_num, "pin": moh_pin, "error": "Missing student first and last name."})
                    continue

            # Program determination
            raw_prog = row.get("program") or default_program or "nursing"
            try:
                norm_prog = normalize_program(raw_prog)
            except ValueError:
                norm_prog = "nursing" if "nur" in str(raw_prog).lower() else "midwifery" if "mid" in str(raw_prog).lower() else "nursing"

            # Class and Year
            raw_class = row.get("class_name") or default_class or "100"
            norm_class = normalize_class_name(raw_class)
            raw_year = row.get("admission_year") or default_year
            year_int = normalize_year(raw_year)

            # MOH PIN / Index Determination:
            # If missing or blank, auto-generate a unique provisional MOH PIN
            if not moh_pin:
                prog_abbr = "NUR" if norm_prog == "nursing" else "MID"
                clean_yr = str(year_int)
                moh_pin = f"MOH-{prog_abbr}-{clean_yr}-{secrets.randbelow(900000) + 100000}"
                while moh_pin in existing_pins or moh_pin in seen_pins_in_batch:
                    moh_pin = f"MOH-{prog_abbr}-{clean_yr}-{secrets.randbelow(900000) + 100000}"

            # If serial_number is missing or empty, auto-generate a secure voucher passcode
            if not serial_number:
                serial_number = f"SN-{secrets.randbelow(900000) + 100000}"

            # Check duplicate within CSV batch
            if moh_pin in seen_pins_in_batch:
                errors.append({
                    "row": row_num,
                    "pin": moh_pin,
                    "error": f"Duplicate MOH PIN '{moh_pin}' repeated in this file.",
                })
                continue
            seen_pins_in_batch.add(moh_pin)

            # Check duplicate in database
            if moh_pin in existing_pins:
                errors.append({
                    "row": row_num,
                    "pin": moh_pin,
                    "error": f"MOH PIN '{moh_pin}' is already registered in the system.",
                })
                continue

            # Generate institutional ASDAM Student ID
            student_id = generate_asdam_student_id(
                program=norm_prog,
                class_name=norm_class,
                year=year_int,
                commit=not dry_run,
            )

            phone = row.get("phone", "").strip()
            raw_email = row.get("email", "").strip().lower()

            # Email provisioning: use provided if valid and not taken; otherwise generate institutional placeholder
            if raw_email and raw_email not in existing_emails:
                email_to_use = raw_email
            else:
                clean_id_slug = student_id.lower().replace("/", ".").replace("-", ".")
                email_to_use = f"{clean_id_slug}@student.asdam.edu.gh"
                if email_to_use in existing_emails:
                    email_to_use = f"{clean_id_slug}.{moh_pin.lower()[:6]}@student.asdam.edu.gh"

            existing_emails.add(email_to_use)
            existing_pins.add(moh_pin)

            student_record = {
                "student_id": student_id,
                "first_name": first_name,
                "last_name": last_name,
                "full_name": f"{first_name} {last_name}".strip(),
                "moh_pin": moh_pin,
                "serial_number": serial_number,
                "program": norm_prog,
                "program_label": "Nursing" if norm_prog == "nursing" else "Midwifery",
                "class_name": norm_class,
                "admission_year": year_int,
                "phone": phone,
                "email": email_to_use,
                "is_registered": False,
            }

            if not dry_run:
                user = User(
                    email=email_to_use,
                    student_id=student_id,
                    moh_pin=moh_pin,
                    serial_number=serial_number,
                    program=norm_prog,
                    class_name=norm_class,
                    admission_year=year_int,
                    first_name=first_name,
                    last_name=last_name,
                    role=User.Role.STUDENT,
                    department="Nursing" if norm_prog == "nursing" else "Midwifery",
                    phone=phone,
                    is_active=True,
                    is_registered=False,
                )
                user.set_password(serial_number)
                user.save()

                UserProfile.objects.create(
                    user=user,
                    academic_level=norm_class,
                    enrollment_year=year_int,
                    major="Nursing" if norm_prog == "nursing" else "Midwifery",
                )
                student_record["user_id"] = str(user.id)

            imported_students.append(student_record)

        if dry_run:
            transaction.set_rollback(True)

    # Dispatch welcome notifications asynchronously in background daemon thread
    notifications_count = len(imported_students)
    if not dry_run and imported_students:
        def _async_notify(students_list):
            from apps.notifications.tasks import dispatch_welcome_notifications
            for student in students_list:
                uid = student.get("user_id")
                serial = student.get("serial_number")
                if uid and serial:
                    try:
                        dispatch_welcome_notifications(user_id=uid, raw_password=serial)
                    except Exception as notif_err:
                        logger.warning("Failed to dispatch welcome notification for user %s: %s", uid, notif_err)

        threading.Thread(target=_async_notify, args=(list(imported_students),), daemon=True).start()

    success_flag = len(imported_students) > 0 or (dry_run and len(rows_to_process) > 0)

    return {
        "success": success_flag,
        "total_rows": len(rows_to_process),
        "imported_count": len(imported_students),
        "notifications_count": notifications_count,
        "skipped_count": len(errors),
        "dry_run": dry_run,
        "students": imported_students,
        "errors": errors,
    }
