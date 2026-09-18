"""
Roster Ingestion Service.
Parses, validates, and provisions student cohorts from Ministry of Health (MOH)
admissions lists with automated ASDAM Student ID generation.
"""
import io
import csv
import logging
from typing import Dict, Any, List, Optional
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

HEADER_MAP = {
    # MOH PIN variations
    "moh_pin": "moh_pin",
    "pin": "moh_pin",
    "moh pin": "moh_pin",
    "moh_index": "moh_pin",
    "moh index": "moh_pin",
    "index": "moh_pin",
    "index_number": "moh_pin",
    "index number": "moh_pin",

    # Serial Number variations
    "serial_number": "serial_number",
    "serial": "serial_number",
    "serial_no": "serial_number",
    "serial no": "serial_number",
    "serial number": "serial_number",
    "voucher": "serial_number",
    "voucher_serial": "serial_number",
    "voucher serial": "serial_number",
    "voucher_code": "serial_number",

    # Names
    "first_name": "first_name",
    "firstname": "first_name",
    "first name": "first_name",
    "given_name": "first_name",
    "last_name": "last_name",
    "lastname": "last_name",
    "last name": "last_name",
    "surname": "last_name",
    "name": "full_name",
    "full_name": "full_name",
    "student_name": "full_name",

    # Program / Department
    "program": "program",
    "programme": "program",
    "department": "program",
    "course": "program",

    # Class / Level
    "class": "class_name",
    "class_name": "class_name",
    "level": "class_name",
    "academic_level": "class_name",

    # Year
    "year": "admission_year",
    "admission_year": "admission_year",
    "enrollment_year": "admission_year",

    # Contact
    "phone": "phone",
    "phone_number": "phone",
    "mobile": "phone",
    "email": "email",
    "email_address": "email",
}


def normalize_headers(raw_headers: List[str]) -> Dict[str, str]:
    """Map raw CSV header keys to standardized internal keys."""
    mapping = {}
    for h in raw_headers:
        if not h:
            continue
        cleaned = str(h).strip().lower().replace("-", "_")
        target = HEADER_MAP.get(cleaned)
        if target:
            mapping[h] = target
        else:
            # check without underscores/spaces
            compressed = cleaned.replace("_", "").replace(" ", "")
            for map_key, map_target in HEADER_MAP.items():
                if map_key.replace("_", "").replace(" ", "") == compressed:
                    mapping[h] = map_target
                    break
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


def process_roster_csv(
    csv_file,
    default_program: Optional[str] = None,
    default_class: str = "100",
    default_year: Optional[int] = None,
    dry_run: bool = False,
    uploader: Optional[User] = None,
) -> Dict[str, Any]:
    """
    Parse, validate, and import an MOH student roster CSV.
    Operates inside an atomic transaction.
    """
    if hasattr(csv_file, "read"):
        content = csv_file.read()
    elif isinstance(csv_file, bytes):
        content = csv_file
    elif isinstance(csv_file, str):
        content = csv_file.encode("utf-8")
    else:
        raise ValueError("Invalid file object provided.")

    # Decode handling UTF-8 BOM
    if isinstance(content, bytes):
        try:
            text = content.decode("utf-8-sig")
        except UnicodeDecodeError:
            text = content.decode("latin-1")
    else:
        text = str(content)

    text = text.strip()
    if not text:
        return {
            "success": False,
            "total_rows": 0,
            "imported_count": 0,
            "skipped_count": 0,
            "students": [],
            "errors": [{"row": 0, "error": "The uploaded CSV file is empty."}],
        }

    # Detect delimiter
    sample = text[:2048]
    delimiter = ","
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",\t;|")
        delimiter = dialect.delimiter
    except Exception:
        delimiter = ","

    reader = csv.reader(io.StringIO(text), delimiter=delimiter)
    try:
        raw_headers = next(reader)
    except StopIteration:
        return {
            "success": False,
            "total_rows": 0,
            "imported_count": 0,
            "skipped_count": 0,
            "students": [],
            "errors": [{"row": 0, "error": "CSV file does not contain a header row."}],
        }

    header_map = normalize_headers(raw_headers)
    required_keys = {"moh_pin", "serial_number"}
    mapped_targets = set(header_map.values())
    missing_required = required_keys - mapped_targets
    if missing_required:
        missing_str = ", ".join(missing_required)
        return {
            "success": False,
            "total_rows": 0,
            "imported_count": 0,
            "skipped_count": 0,
            "students": [],
            "errors": [{"row": 1, "error": f"Missing required column(s): {missing_str}. Headers detected: {list(header_map.keys())}"}],
        }

    imported_students: List[Dict[str, Any]] = []
    errors: List[Dict[str, Any]] = []
    seen_pins_in_batch = set()
    seen_serials_in_batch = set()

    # Pre-load existing MOH PINs to avoid N+1 queries
    existing_pins = set(User.objects.exclude(moh_pin__isnull=True).exclude(moh_pin="").values_list("moh_pin", flat=True))
    existing_emails = set(User.objects.values_list("email", flat=True))

    row_index = 1  # 1 is header
    rows_to_process = []

    for raw_row in reader:
        row_index += 1
        if not raw_row or not any(str(c).strip() for c in raw_row):
            continue  # ignore completely empty rows

        row_dict = {}
        for idx, val in enumerate(raw_row):
            if idx < len(raw_headers):
                raw_h = raw_headers[idx]
                target_k = header_map.get(raw_h)
                if target_k:
                    row_dict[target_k] = str(val).strip()

        rows_to_process.append((row_index, row_dict))

    if not rows_to_process:
        return {
            "success": False,
            "total_rows": 0,
            "imported_count": 0,
            "skipped_count": 0,
            "students": [],
            "errors": [{"row": 0, "error": "No student data rows found in CSV."}],
        }

    # Atomic processing
    with transaction.atomic():
        for row_num, row in rows_to_process:
            moh_pin = row.get("moh_pin", "").strip().upper()
            serial_number = row.get("serial_number", "").strip()

            if not moh_pin:
                errors.append({"row": row_num, "pin": "", "error": "Missing MOH PIN."})
                continue

            if not serial_number:
                errors.append({"row": row_num, "pin": moh_pin, "error": "Missing Serial Number."})
                continue

            # Check duplicate within CSV batch
            if moh_pin in seen_pins_in_batch:
                errors.append({"row": row_num, "pin": moh_pin, "error": f"Duplicate MOH PIN '{moh_pin}' repeated in this file."})
                continue
            seen_pins_in_batch.add(moh_pin)

            # Check duplicate in database
            if moh_pin in existing_pins:
                errors.append({"row": row_num, "pin": moh_pin, "error": f"MOH PIN '{moh_pin}' is already registered in the system."})
                continue

            # Extract names
            first_name = row.get("first_name", "").strip()
            last_name = row.get("last_name", "").strip()
            if not first_name or not last_name:
                full_name = row.get("full_name", "").strip()
                if full_name:
                    parts = full_name.split(None, 1)
                    first_name = parts[0]
                    last_name = parts[1] if len(parts) > 1 else "Student"
                else:
                    errors.append({"row": row_num, "pin": moh_pin, "error": "Missing student first and last name."})
                    continue

            # Program determination
            raw_prog = row.get("program") or default_program or "nursing"
            try:
                norm_prog = normalize_program(raw_prog)
            except ValueError as e:
                errors.append({"row": row_num, "pin": moh_pin, "error": str(e)})
                continue

            # Class and Year
            raw_class = row.get("class_name") or default_class or "100"
            norm_class = normalize_class_name(raw_class)
            raw_year = row.get("admission_year") or default_year
            year_int = normalize_year(raw_year)

            # Generate institutional ASDAM Student ID
            student_id = generate_asdam_student_id(
                program=norm_prog,
                class_name=norm_class,
                year=year_int,
                commit=not dry_run
            )

            phone = row.get("phone", "").strip()
            raw_email = row.get("email", "").strip().lower()

            # Email provisioning: use provided if valid and not taken; otherwise generate institutional placeholder
            if raw_email and raw_email not in existing_emails:
                email_to_use = raw_email
            else:
                clean_id_slug = student_id.lower().replace("/", ".").replace("-", ".")
                email_to_use = f"{clean_id_slug}@student.asdam.edu.gh"
                # If collision, append pin suffix
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
                # Hash initial password from serial number
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
            # Explicit rollback for dry run
            transaction.set_rollback(True)

    # Dispatch welcome credentials notifications (SMS & Email) after transaction commits
    notifications_count = 0
    if not dry_run:
        from apps.notifications.tasks import dispatch_welcome_notifications
        for student in imported_students:
            uid = student.get("user_id")
            serial = student.get("serial_number")
            if uid and serial:
                try:
                    dispatch_welcome_notifications(user_id=uid, raw_password=serial)
                    notifications_count += 1
                except Exception as notif_err:
                    logger.warning("Failed to dispatch welcome notification for user %s: %s", uid, notif_err)

    return {
        "success": True,
        "total_rows": len(rows_to_process),
        "imported_count": len(imported_students),
        "notifications_count": notifications_count,
        "skipped_count": len(errors),
        "dry_run": dry_run,
        "students": imported_students,
        "errors": errors,
    }

