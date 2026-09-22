"""
Constants and registry for Institutional Roles and Granular Functional Permissions.

Supports canonical roles:
- super_admin (Super Admin)
- academic_officer (Academic Officer)
- head_of_department (Head of Department)
- finance (Finance Officer)
- lecturer (Lecturer)
- student (Student)

Also provides normalization for legacy aliases ('admin', 'staff', 'instructor', 'departmental-head').
"""
from typing import List, Dict, Any, Set


class RoleChoice:
    SUPER_ADMIN = "super_admin"
    ACADEMIC_OFFICER = "academic_officer"
    HEAD_OF_DEPARTMENT = "head_of_department"
    FINANCE = "finance"
    LECTURER = "lecturer"
    STUDENT = "student"

    CHOICES = [
        (SUPER_ADMIN, "Super Admin"),
        (ACADEMIC_OFFICER, "Academic Officer"),
        (HEAD_OF_DEPARTMENT, "Head of Department"),
        (FINANCE, "Finance Officer"),
        (LECTURER, "Lecturer"),
        (STUDENT, "Student"),
    ]


ROLE_ALIASES: Dict[str, str] = {
    # Super Admin
    "admin": RoleChoice.SUPER_ADMIN,
    "super_admin": RoleChoice.SUPER_ADMIN,
    "super-admin": RoleChoice.SUPER_ADMIN,
    # Academic Officer
    "staff": RoleChoice.ACADEMIC_OFFICER,
    "academic_officer": RoleChoice.ACADEMIC_OFFICER,
    "academic-officer": RoleChoice.ACADEMIC_OFFICER,
    "officer": RoleChoice.ACADEMIC_OFFICER,
    # Head of Department
    "head_of_department": RoleChoice.HEAD_OF_DEPARTMENT,
    "head-of-department": RoleChoice.HEAD_OF_DEPARTMENT,
    "departmental-head": RoleChoice.HEAD_OF_DEPARTMENT,
    "departmental_head": RoleChoice.HEAD_OF_DEPARTMENT,
    "hod": RoleChoice.HEAD_OF_DEPARTMENT,
    # Finance
    "finance": RoleChoice.FINANCE,
    "finance_officer": RoleChoice.FINANCE,
    "finance-officer": RoleChoice.FINANCE,
    "bursar": RoleChoice.FINANCE,
    # Lecturer
    "lecturer": RoleChoice.LECTURER,
    "instructor": RoleChoice.LECTURER,
    "faculty": RoleChoice.LECTURER,
    # Student
    "student": RoleChoice.STUDENT,
}


def normalize_role(role_val: str) -> str:
    """Normalize input role strings, handling hyphens, uppercase, and legacy aliases."""
    if not role_val:
        return RoleChoice.STUDENT
    cleaned = str(role_val).strip().lower().replace(" ", "_")
    return ROLE_ALIASES.get(cleaned, cleaned)


# ── GRANULAR FUNCTIONAL CAPABILITIES ──────────────────────────────────────────
PORTAL_FUNCTIONS: List[Dict[str, str]] = [
    # Admissions & Registry
    {
        "code": "students.view",
        "name": "View Student Directory",
        "category": "Admissions & Registry",
        "description": "View institutional student roster, academic status, and profiles.",
    },
    {
        "code": "students.create",
        "name": "Register / Admit Students",
        "category": "Admissions & Registry",
        "description": "Onboard and register new students into programs and index sequences.",
    },
    {
        "code": "students.edit",
        "name": "Modify Student Records",
        "category": "Admissions & Registry",
        "description": "Edit student biographical details, contact information, and demographics.",
    },
    {
        "code": "students.promote",
        "name": "Academic Promotion / Demotion",
        "category": "Admissions & Registry",
        "description": "Authorize single and cohort academic promotions, level changes, and repeats.",
    },
    {
        "code": "students.withdraw",
        "name": "Withdrawals & Reinstatements",
        "category": "Admissions & Registry",
        "description": "Process academic leaves, official withdrawals, and reinstatements.",
    },
    {
        "code": "students.delete",
        "name": "Student Lifecycle Deletion",
        "category": "Admissions & Registry",
        "description": "Soft-delete, restore, or precheck student record retention.",
    },
    {
        "code": "students.export",
        "name": "Export Student Records",
        "category": "Admissions & Registry",
        "description": "Download institutional CSV rosters and demographic audits.",
    },

    # Academics & Curriculum
    {
        "code": "courses.view",
        "name": "View Courses & Catalog",
        "category": "Academics & Curriculum",
        "description": "Access full course catalog, syllabus descriptions, and schedules.",
    },
    {
        "code": "courses.create",
        "name": "Create Courses",
        "category": "Academics & Curriculum",
        "description": "Define new curriculum courses, credits, and requirements.",
    },
    {
        "code": "courses.edit",
        "name": "Edit Course & Syllabi",
        "category": "Academics & Curriculum",
        "description": "Update course details, descriptions, prerequisites, and max capacities.",
    },
    {
        "code": "courses.publish",
        "name": "Publish / Archive Courses",
        "category": "Academics & Curriculum",
        "description": "Manage publication state and semester availability for registration.",
    },
    {
        "code": "schedules.manage",
        "name": "Manage Class Schedules",
        "category": "Academics & Curriculum",
        "description": "Configure time slots, lecture rooms, and recurring weekly lessons.",
    },
    {
        "code": "registration_windows.manage",
        "name": "Manage Registration Windows",
        "category": "Academics & Curriculum",
        "description": "Open and close semester course registration windows and deadlines.",
    },

    # Departmental Operations
    {
        "code": "department.view_roster",
        "name": "View Department Directory",
        "category": "Departmental Operations",
        "description": "Access faculty, staff, and student directories within own department.",
    },
    {
        "code": "department.assign_lecturers",
        "name": "Assign Lecturers to Courses",
        "category": "Departmental Operations",
        "description": "Allocate instructors and teaching assistants to scheduled courses.",
    },
    {
        "code": "department.approve_courses",
        "name": "Approve Departmental Curricula",
        "category": "Departmental Operations",
        "description": "Sign off on department course offerings before university publication.",
    },
    {
        "code": "department.analytics",
        "name": "Departmental Analytics",
        "category": "Departmental Operations",
        "description": "View department performance, passing rates, and enrollment metrics.",
    },

    # Grading & Assessments
    {
        "code": "grades.view",
        "name": "View Grades",
        "category": "Grading & Assessments",
        "description": "View student assessment grades, midterms, and finals.",
    },
    {
        "code": "grades.enter",
        "name": "Enter / Edit Grades",
        "category": "Grading & Assessments",
        "description": "Enter raw assessment scores and feedback for enrolled students.",
    },
    {
        "code": "grades.submit_batch",
        "name": "Submit Grade Batches",
        "category": "Grading & Assessments",
        "description": "Submit finalized grade batches for administrative moderation.",
    },
    {
        "code": "grades.approve_batch",
        "name": "Approve / Publish Grade Batches",
        "category": "Grading & Assessments",
        "description": "Moderate, approve, and officially publish submitted grade batches.",
    },
    {
        "code": "transcripts.generate",
        "name": "Generate Official Transcripts",
        "category": "Grading & Assessments",
        "description": "Generate official semester and cumulative transcripts with GPA certification.",
    },

    # Financial Management
    {
        "code": "fees.view",
        "name": "View Fee Structures & Invoices",
        "category": "Financial Management",
        "description": "Inspect student billing ledgers, fees, and invoice breakdown.",
    },
    {
        "code": "fees.configure",
        "name": "Configure Fee Structures",
        "category": "Financial Management",
        "description": "Create and update program and semester fee schedules and dues.",
    },
    {
        "code": "payments.record",
        "name": "Record & Reconcile Payments",
        "category": "Financial Management",
        "description": "Record bank transfers, receipts, and process student fee reconciliations.",
    },
    {
        "code": "financials.reports",
        "name": "Financial Treasury Reports",
        "category": "Financial Management",
        "description": "Access revenue analytics, debt aging lists, and financial audits.",
    },
    {
        "code": "holds.override",
        "name": "Manage Financial Holds",
        "category": "Financial Management",
        "description": "Apply or lift financial registration holds on delinquent student accounts.",
    },

    # Security & Administration
    {
        "code": "users.manage_roles",
        "name": "Manage Roles & Permissions",
        "category": "Security & System",
        "description": "Assign institutional roles and grant/revoke functional capabilities.",
    },
    {
        "code": "system.settings",
        "name": "System Configuration",
        "category": "Security & System",
        "description": "Configure portal global parameters, email templates, and integrations.",
    },
    {
        "code": "audit.view_logs",
        "name": "View Audit & Progression Logs",
        "category": "Security & System",
        "description": "Inspect immutable progression and security activity audit trails.",
    },
]

ALL_FUNCTION_CODES: Set[str] = {f["code"] for f in PORTAL_FUNCTIONS}


# ── INSTITUTIONAL ROLE DEFINITIONS & BASELINE FUNCTIONS ───────────────────────
PORTAL_ROLES: List[Dict[str, Any]] = [
    {
        "code": RoleChoice.SUPER_ADMIN,
        "name": "Super Admin",
        "description": "Full institutional authority across security, users, academics, finance, and system auditing.",
        "badge_color": "#4f46e5",  # Indigo
        "default_functions": list(ALL_FUNCTION_CODES),
    },
    {
        "code": RoleChoice.ACADEMIC_OFFICER,
        "name": "Academic Officer",
        "description": "Oversees admissions, academic progression, curriculum schedules, and official transcripts.",
        "badge_color": "#e11d48",  # Rose
        "default_functions": [
            "students.view",
            "students.create",
            "students.edit",
            "students.promote",
            "students.withdraw",
            "students.delete",
            "students.export",
            "courses.view",
            "courses.create",
            "courses.edit",
            "courses.publish",
            "schedules.manage",
            "registration_windows.manage",
            "grades.view",
            "grades.approve_batch",
            "transcripts.generate",
            "audit.view_logs",
        ],
    },
    {
        "code": RoleChoice.HEAD_OF_DEPARTMENT,
        "name": "Head of Department",
        "description": "Leads department faculty, assigns courses to lecturers, reviews grades, and oversees curriculum.",
        "badge_color": "#0284c7",  # Sky Blue
        "default_functions": [
            "courses.view",
            "courses.create",
            "courses.edit",
            "courses.publish",
            "schedules.manage",
            "department.view_roster",
            "department.assign_lecturers",
            "department.approve_courses",
            "department.analytics",
            "grades.view",
            "grades.approve_batch",
            "transcripts.generate",
            "students.view",
            "students.export",
        ],
    },
    {
        "code": RoleChoice.FINANCE,
        "name": "Finance Officer",
        "description": "Manages tuition structures, invoices, payment receipts, student balances, and financial holds.",
        "badge_color": "#d97706",  # Amber
        "default_functions": [
            "fees.view",
            "fees.configure",
            "payments.record",
            "financials.reports",
            "holds.override",
            "students.view",
            "students.export",
        ],
    },
    {
        "code": RoleChoice.LECTURER,
        "name": "Lecturer",
        "description": "Instructs classes, creates assignments, grades student submissions, and submits grade batches.",
        "badge_color": "#7c3aed",  # Violet
        "default_functions": [
            "courses.view",
            "grades.view",
            "grades.enter",
            "grades.submit_batch",
            "students.view",
        ],
    },
    {
        "code": RoleChoice.STUDENT,
        "name": "Student",
        "description": "Registers for courses, views schedules and course materials, tracks grades, and pays fees.",
        "badge_color": "#059669",  # Emerald
        "default_functions": [
            "courses.view",
            "grades.view",
            "fees.view",
        ],
    },
]

ROLE_MAP: Dict[str, Dict[str, Any]] = {
    r["code"]: r for r in PORTAL_ROLES
}


def get_default_functions_for_role(role_val: str) -> List[str]:
    """Retrieve standard baseline capabilities for a given role (canonical or alias)."""
    norm = normalize_role(role_val)
    role_def = ROLE_MAP.get(norm)
    if role_def:
        return list(role_def["default_functions"])
    return []


def get_effective_functions(role_val: str, assigned_functions: List[str] | None = None) -> List[str]:
    """
    Compute effective capabilities:
    Union of baseline capabilities for the assigned role and any custom assigned capabilities.
    """
    defaults = set(get_default_functions_for_role(role_val))
    if assigned_functions:
        defaults.update(f for f in assigned_functions if f in ALL_FUNCTION_CODES)
    return sorted(list(defaults))
