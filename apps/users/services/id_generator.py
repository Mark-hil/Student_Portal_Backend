"""
Institutional ASDAM Student ID Generator.
Ensures unique, sequential, concurrency-safe student IDs distinguishing
Nursing (NUR) and Midwifery (MID).
"""
import re
import logging
from django.db import transaction
from django.utils import timezone
from apps.users.models import IDSequence, User

logger = logging.getLogger(__name__)

PROGRAM_CODES = {
    "nursing": "NUR",
    "midwifery": "MID",
}

# Reverse mapping
CODE_TO_PROGRAM = {
    "NUR": "nursing",
    "MID": "midwifery",
}


def normalize_program(program_input: str) -> str:
    """Normalize user/CSV program text to either 'nursing' or 'midwifery'."""
    p = str(program_input or "").strip().lower()
    if "midwi" in p or p in ("mid", "rm"):
        return "midwifery"
    if "nurs" in p or p in ("nur", "rgn"):
        return "nursing"
    raise ValueError(f"Unknown program '{program_input}'. Valid programs are 'Nursing' or 'Midwifery'.")


def get_program_code(program: str) -> str:
    """Returns 'NUR' or 'MID'."""
    norm = normalize_program(program)
    return PROGRAM_CODES[norm]


def normalize_class_name(class_input: str) -> str:
    """Normalize class name into a clean code, e.g., 'Level 100' -> '100', 'Class 1' -> 'CL1', '100' -> '100'."""
    c = str(class_input or "").strip()
    if not c:
        return "100"
    # Remove 'Level ' prefix if present e.g. 'Level 100' -> '100'
    c_clean = re.sub(r'(?i)^level\s*', '', c).strip()
    # Replace spaces or slashes with hyphens
    c_clean = re.sub(r'[\s/]+', '-', c_clean).upper()
    return c_clean or "100"


def normalize_year(year_input) -> int:
    """Normalize year to integer (e.g. 2026)."""
    if not year_input:
        return timezone.now().year
    try:
        y = int(year_input)
        if y < 100:  # e.g. 26 -> 2026
            y += 2000
        return y
    except (ValueError, TypeError):
        return timezone.now().year


def generate_asdam_student_id(
    program: str,
    class_name: str = "",
    year: int = None,
    commit: bool = True
) -> str:
    """
    Concurrency-safe generation of institutional ASDAM Student ID.
    Format:
      ASDAM/NUR/{YEAR_2DIGIT}/{SEQ:03d}
      or ASDAM/MID/{YEAR_2DIGIT}/{SEQ:03d}
    Example:
      Nursing:   ASDAM/NUR/26/001
      Midwifery: ASDAM/MID/26/001
    """
    norm_program = normalize_program(program)
    code = get_program_code(norm_program)
    year_int = normalize_year(year)
    year_2digit = str(year_int)[-2:]

    prefix = f"ASDAM/{code}/{year_2digit}"

    with transaction.atomic():
        seq, _ = IDSequence.objects.select_for_update().get_or_create(
            program=norm_program,
            class_name="",
            year=year_int,
            defaults={"last_number": 0}
        )

        # Baseline sync: If sequence is 0, verify against existing student IDs in User table
        if seq.last_number == 0:
            existing_ids = User.objects.filter(student_id__startswith=f"{prefix}/").values_list("student_id", flat=True)
            max_num = 0
            for sid in existing_ids:
                parts = sid.split("/")
                if parts and parts[-1].isdigit():
                    max_num = max(max_num, int(parts[-1]))
            if max_num > 0:
                seq.last_number = max_num

        next_number = seq.last_number + 1

        if commit:
            seq.last_number = next_number
            seq.save(update_fields=["last_number", "updated_at"])

        return f"{prefix}/{next_number:03d}"

