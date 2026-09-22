import os
import django
from datetime import timedelta, time
from decimal import Decimal

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings.development')
django.setup()

from django.contrib.auth import get_user_model
from django.utils import timezone
from apps.courses.models import Course, Category, Enrollment, RegistrationWindow, CourseSchedule, Lesson
from apps.grades.models import Assignment, Grade, GradeBatch, Submission, Transcript, SemesterRecord
from apps.grades.gpa import letter_from_pct

User = get_user_model()

def seed():
    print("🚀 Starting Comprehensive Database Seed...")

    # ── 1. USERS ─────────────────────────────────────────────────────────────
    print("1. Creating Users for all 6 Institutional Roles...")
    admin, _ = User.objects.get_or_create(
        email="admin@uniportal.edu", 
        defaults={
            "first_name": "Alice",
            "last_name": "Admin",
            "role": "super_admin",
            "is_staff": True,
            "is_superuser": True,
            "department": "IT & Systems",
            "email_verified": True,
        }
    )
    admin.set_password("password123")
    admin.role = "super_admin"
    admin.is_staff = True
    admin.is_superuser = True
    admin.save()

    academic_officer, _ = User.objects.get_or_create(
        email="academic@uniportal.edu",
        defaults={
            "first_name": "Sarah",
            "last_name": "Connor",
            "role": "academic_officer",
            "is_staff": True,
            "department": "Academic Affairs & Registrar",
            "email_verified": True,
        }
    )
    academic_officer.set_password("password123")
    academic_officer.role = "academic_officer"
    academic_officer.is_staff = True
    academic_officer.save()

    # Legacy alias staff user
    staff, _ = User.objects.get_or_create(
        email="staff@uniportal.edu",
        defaults={
            "first_name": "Sarah",
            "last_name": "Connor",
            "role": "academic_officer",
            "is_staff": True,
            "department": "Academic Registrar & Records",
            "email_verified": True,
        }
    )
    staff.set_password("password123")
    staff.role = "academic_officer"
    staff.is_staff = True
    staff.save()

    hod, _ = User.objects.get_or_create(
        email="hod@uniportal.edu",
        defaults={
            "first_name": "Dr. Margaret",
            "last_name": "Hamilton",
            "role": "head_of_department",
            "is_staff": True,
            "department": "Computer Science",
            "bio": "Head of Computer Science Department, leading software engineering and curriculum quality.",
            "email_verified": True,
        }
    )
    hod.set_password("password123")
    hod.role = "head_of_department"
    hod.is_staff = True
    hod.save()

    finance, _ = User.objects.get_or_create(
        email="finance@uniportal.edu",
        defaults={
            "first_name": "Marcus",
            "last_name": "Thorne",
            "role": "finance",
            "is_staff": False,
            "department": "Treasury & Student Accounts",
            "email_verified": True,
        }
    )
    finance.set_password("password123")
    finance.role = "finance"
    finance.save()

    lecturer, _ = User.objects.get_or_create(
        email="lecturer@uniportal.edu", 
        defaults={
            "first_name": "Dr. Alan",
            "last_name": "Turing",
            "role": "lecturer",
            "department": "Computer Science",
            "bio": "Professor of Computer Science specializing in Algorithms, Complexity Theory, and Machine Learning.",
            "email_verified": True,
        }
    )
    lecturer.set_password("password123")
    lecturer.role = "lecturer"
    lecturer.save()

    student, _ = User.objects.get_or_create(
        email="student@uniportal.edu", 
        defaults={
            "first_name": "Alex",
            "last_name": "Mercer",
            "role": "student",
            "student_id": "STU-2024-8891",
            "department": "Computer Science",
            "bio": "Third-year undergraduate student focusing on Software Engineering and Artificial Intelligence.",
            "email_verified": True,
        }
    )
    student.set_password("password123")
    student.role = "student"
    student.student_id = "STU-2024-8891"
    student.department = "Computer Science"
    student.save()

    student2, _ = User.objects.get_or_create(
        email="student2@uniportal.edu", 
        defaults={
            "first_name": "Beatrice",
            "last_name": "Vance",
            "role": "student",
            "student_id": "STU-2024-8892",
            "department": "Computer Science",
            "email_verified": True,
        }
    )
    student2.set_password("password123")
    student2.role = "student"
    student2.student_id = "STU-2024-8892"
    student2.save()

    student3, _ = User.objects.get_or_create(
        email="student3@uniportal.edu", 
        defaults={
            "first_name": "Clara",
            "last_name": "Oswald",
            "role": "student",
            "student_id": "STU-2024-8893",
            "department": "Data Science",
            "email_verified": True,
        }
    )
    student3.set_password("password123")
    student3.role = "student"
    student3.student_id = "STU-2024-8893"
    student3.save()

    # ── 2. REGISTRATION WINDOWS ──────────────────────────────────────────────
    print("2. Creating Registration Windows...")
    now = timezone.now()
    RegistrationWindow.objects.update_or_create(
        semester="2025-SPRING",
        defaults={
            "opens_at": now - timedelta(days=30),
            "closes_at": now + timedelta(days=60),
            "is_active": True,
        }
    )
    RegistrationWindow.objects.update_or_create(
        semester="2024-FALL",
        defaults={
            "opens_at": now - timedelta(days=200),
            "closes_at": now - timedelta(days=120),
            "is_active": False,
        }
    )

    # ── 3. CATEGORIES ────────────────────────────────────────────────────────
    print("3. Creating Course Categories...")
    cat_cs, _ = Category.objects.get_or_create(name="Computer Science", slug="computer-science", defaults={"description": "Algorithms, Systems, and Software", "icon": "Code"})
    cat_math, _ = Category.objects.get_or_create(name="Mathematics", slug="mathematics", defaults={"description": "Pure & Applied Mathematics", "icon": "Divide"})
    cat_ds, _ = Category.objects.get_or_create(name="Data Science", slug="data-science", defaults={"description": "Machine Learning, Analytics & Statistics", "icon": "BarChart"})
    cat_phys, _ = Category.objects.get_or_create(name="Natural Sciences", slug="natural-sciences", defaults={"description": "Physics and Applied Mechanics", "icon": "Atom"})

    # ── 4. COURSES ───────────────────────────────────────────────────────────
    print("4. Creating Courses...")
    # Historical Courses (for Transcript)
    cs101, _ = Course.objects.update_or_create(
        code="CS101",
        defaults={
            "title": "Intro to Computer Science & Python",
            "slug": "cs101-intro-cs",
            "description": "Foundational programming concepts, control flow, functions, and object-oriented paradigms.",
            "category": cat_cs,
            "credits": 4,
            "max_students": 120,
            "semester": "2024-SPRING",
            "status": Course.Status.ARCHIVED,
            "start_date": (now - timedelta(days=365)).date(),
            "end_date": (now - timedelta(days=275)).date(),
        }
    )
    cs101.instructors.add(lecturer)

    math101, _ = Course.objects.update_or_create(
        code="MATH101",
        defaults={
            "title": "Calculus I: Single Variable",
            "slug": "math101-calc-1",
            "description": "Limits, derivatives, definite integrals, and fundamental theorems with scientific applications.",
            "category": cat_math,
            "credits": 4,
            "max_students": 100,
            "semester": "2024-SPRING",
            "status": Course.Status.ARCHIVED,
            "start_date": (now - timedelta(days=365)).date(),
            "end_date": (now - timedelta(days=275)).date(),
        }
    )

    eng101, _ = Course.objects.update_or_create(
        code="ENG101",
        defaults={
            "title": "Technical Writing & Communication",
            "slug": "eng101-tech-writing",
            "description": "Professional engineering documentation, research papers, and technical presentations.",
            "category": cat_cs,
            "credits": 3,
            "max_students": 80,
            "semester": "2024-SPRING",
            "status": Course.Status.ARCHIVED,
            "start_date": (now - timedelta(days=365)).date(),
            "end_date": (now - timedelta(days=275)).date(),
        }
    )

    cs201, _ = Course.objects.update_or_create(
        code="CS201",
        defaults={
            "title": "Data Structures & OOP Design",
            "slug": "cs201-data-structures",
            "description": "Linked lists, trees, graphs, heaps, hash tables, and asymptotic algorithm complexity analysis.",
            "category": cat_cs,
            "credits": 4,
            "max_students": 90,
            "semester": "2024-FALL",
            "status": Course.Status.ARCHIVED,
            "start_date": (now - timedelta(days=240)).date(),
            "end_date": (now - timedelta(days=150)).date(),
        }
    )
    cs201.instructors.add(lecturer)

    math102, _ = Course.objects.update_or_create(
        code="MATH102",
        defaults={
            "title": "Calculus II & Discrete Structures",
            "slug": "math102-calc-2",
            "description": "Integration techniques, infinite series, recurrence relations, and combinatorial logic.",
            "category": cat_math,
            "credits": 4,
            "max_students": 85,
            "semester": "2024-FALL",
            "status": Course.Status.ARCHIVED,
            "start_date": (now - timedelta(days=240)).date(),
            "end_date": (now - timedelta(days=150)).date(),
        }
    )

    phy101, _ = Course.objects.update_or_create(
        code="PHY101",
        defaults={
            "title": "Physics: Mechanics & Waves",
            "slug": "phy101-mechanics",
            "description": "Newtonian mechanics, rotational dynamics, work-energy principles, and oscillatory wave motion.",
            "category": cat_phys,
            "credits": 4,
            "max_students": 70,
            "semester": "2024-FALL",
            "status": Course.Status.ARCHIVED,
            "start_date": (now - timedelta(days=240)).date(),
            "end_date": (now - timedelta(days=150)).date(),
        }
    )

    # Current Semester Courses (2025-SPRING)
    cs400, _ = Course.objects.update_or_create(
        code="CS400",
        defaults={
            "title": "Advanced Algorithms & Optimization",
            "slug": "cs400-advanced-algorithms",
            "description": "Dynamic programming, max flow, NP-completeness, randomized and approximation algorithms.",
            "category": cat_cs,
            "credits": 4,
            "max_students": 60,
            "semester": "2025-SPRING",
            "status": Course.Status.ACTIVE,
            "start_date": (now - timedelta(days=30)).date(),
            "end_date": (now + timedelta(days=90)).date(),
        }
    )
    cs400.instructors.add(lecturer)

    cs301, _ = Course.objects.update_or_create(
        code="CS301",
        defaults={
            "title": "Operating Systems & Systems Programming",
            "slug": "cs301-operating-systems",
            "description": "Processes, concurrency, memory management, virtual memory, file systems, and kernel architecture.",
            "category": cat_cs,
            "credits": 4,
            "max_students": 50,
            "semester": "2025-SPRING",
            "status": Course.Status.ACTIVE,
            "start_date": (now - timedelta(days=30)).date(),
            "end_date": (now + timedelta(days=90)).date(),
        }
    )
    cs301.instructors.add(lecturer)

    ds201, _ = Course.objects.update_or_create(
        code="DS201",
        defaults={
            "title": "Machine Learning & Data Intelligence",
            "slug": "ds201-machine-learning",
            "description": "Supervised & unsupervised learning, neural networks, model validation, gradient descent, and PyTorch.",
            "category": cat_ds,
            "credits": 3,
            "max_students": 45,
            "semester": "2025-SPRING",
            "status": Course.Status.ACTIVE,
            "start_date": (now - timedelta(days=30)).date(),
            "end_date": (now + timedelta(days=90)).date(),
        }
    )
    ds201.instructors.add(lecturer)

    math205, _ = Course.objects.update_or_create(
        code="MATH205",
        defaults={
            "title": "Linear Algebra for Computer Science",
            "slug": "math205-linear-algebra",
            "description": "Vector spaces, matrices, eigenvalues, SVD decomposition, and geometric transformations.",
            "category": cat_math,
            "credits": 3,
            "max_students": 55,
            "semester": "2025-SPRING",
            "status": Course.Status.ACTIVE,
            "start_date": (now - timedelta(days=30)).date(),
            "end_date": (now + timedelta(days=90)).date(),
        }
    )

    # ── 5. COURSE SCHEDULES & LESSONS ────────────────────────────────────────
    print("5. Creating Schedules and Lessons...")
    CourseSchedule.objects.update_or_create(
        course=cs400, day_of_week=CourseSchedule.Day.TUESDAY, start_time=time(14, 0),
        defaults={"end_time": time(15, 30), "room": "Turing Lab 204", "is_online": False}
    )
    CourseSchedule.objects.update_or_create(
        course=cs400, day_of_week=CourseSchedule.Day.THURSDAY, start_time=time(14, 0),
        defaults={"end_time": time(15, 30), "room": "Turing Lab 204", "is_online": False}
    )
    CourseSchedule.objects.update_or_create(
        course=cs301, day_of_week=CourseSchedule.Day.MONDAY, start_time=time(10, 0),
        defaults={"end_time": time(11, 30), "room": "Hopper Hall 101", "is_online": False}
    )
    CourseSchedule.objects.update_or_create(
        course=cs301, day_of_week=CourseSchedule.Day.WEDNESDAY, start_time=time(10, 0),
        defaults={"end_time": time(11, 30), "room": "Hopper Hall 101", "is_online": False}
    )

    Lesson.objects.update_or_create(
        course=cs400, order=1, title="Introduction to Asymptotic Complexity & Master Theorem",
        defaults={"lesson_type": Lesson.LessonType.VIDEO, "content": "Review Big-O, Omega, Theta and recursion tree analysis."}
    )
    Lesson.objects.update_or_create(
        course=cs400, order=2, title="Dynamic Programming: 1D & 2D Memoization Patterns",
        defaults={"lesson_type": Lesson.LessonType.READING, "content": "Optimal substructure and overlapping subproblems."}
    )

    # ── 6. ENROLLMENTS ───────────────────────────────────────────────────────
    print("6. Enrolling Students...")
    for c in [cs400, cs301, ds201, math205]:
        Enrollment.objects.update_or_create(
            student=student, course=c,
            defaults={"status": Enrollment.Status.ACTIVE, "enrolled_at": now - timedelta(days=25), "progress_pct": Decimal("45.0")}
        )
        Enrollment.objects.update_or_create(
            student=student2, course=c,
            defaults={"status": Enrollment.Status.ACTIVE, "enrolled_at": now - timedelta(days=24), "progress_pct": Decimal("35.0")}
        )
        Enrollment.objects.update_or_create(
            student=student3, course=c,
            defaults={"status": Enrollment.Status.ACTIVE, "enrolled_at": now - timedelta(days=24), "progress_pct": Decimal("50.0")}
        )

    # ── 7. ASSIGNMENTS, SUBMISSIONS, GRADE BATCHES ────────────────────────────
    print("7. Creating Assignments, Submissions & Grade Batches...")
    # Assignment 1: Published & graded batch
    a1, _ = Assignment.objects.update_or_create(
        course=cs400,
        title="Project 1: Dynamic Programming Solver",
        defaults={
            "assignment_type": "project",
            "max_score": 100,
            "weight": 25,
            "due_date": now - timedelta(days=10),
            "description": "Implement the Knapsack, Matrix Chain Multiplication, and Longest Common Subsequence in Python.",
            "is_published": True,
            "created_by": lecturer,
        }
    )

    # Student submissions
    Submission.objects.update_or_create(
        assignment=a1, student=student,
        defaults={
            "text_content": "GitHub: https://github.com/alex-mercer/dp-solver\nAll test cases pass with optimal time complexity O(n*W).",
            "status": Submission.Status.GRADED,
            "submitted_at": now - timedelta(days=12),
        }
    )
    Submission.objects.update_or_create(
        assignment=a1, student=student2,
        defaults={
            "text_content": "GitHub: https://github.com/beatrice-vance/dp-project\nImplemented bottom-up table and top-down memoization.",
            "status": Submission.Status.GRADED,
            "submitted_at": now - timedelta(days=11),
        }
    )

    # ── CLEANUP OLD STALE TEST RECORDS ───────────────────────────────────────
    print("0. Cleaning up old test/stale records...")
    SemesterRecord.objects.filter(semester__in=["unknown", "FA24", ""]).delete()
    Transcript.objects.filter(semester__in=["unknown", "FA24", ""]).delete()
    Course.objects.filter(code__in=["cf00", "CS102"]).delete()

    # ── 7. ASSIGNMENTS, SUBMISSIONS, GRADE BATCHES & GRADES ──────────────────
    print("7. Creating Assignments, Submissions & Grade Batches...")
    
    # ── CS400 Assignments & Published Grades ──
    cs400_a1, _ = Assignment.objects.update_or_create(
        course=cs400, title="Project 1: Dynamic Programming Solver",
        defaults={"assignment_type": "project", "max_score": 100, "weight": 30, "due_date": now - timedelta(days=20), "is_published": True, "created_by": lecturer}
    )
    cs400_a2, _ = Assignment.objects.update_or_create(
        course=cs400, title="Midterm Exam: Flow & Greedy Strategies",
        defaults={"assignment_type": "exam", "max_score": 100, "weight": 30, "due_date": now - timedelta(days=10), "is_published": True, "created_by": lecturer}
    )
    cs400_a3, _ = Assignment.objects.update_or_create(
        course=cs400, title="Final Project: NP-Hard Optimization",
        defaults={"assignment_type": "project", "max_score": 100, "weight": 40, "due_date": now - timedelta(days=2), "is_published": True, "created_by": lecturer}
    )

    for a in [cs400_a1, cs400_a2, cs400_a3]:
        GradeBatch.objects.update_or_create(
            assignment=a,
            defaults={"status": GradeBatch.Status.PUBLISHED, "submitted_by": lecturer, "reviewed_by": staff, "published_at": now - timedelta(days=1)}
        )

    Grade.objects.update_or_create(assignment=cs400_a1, student=student, defaults={"score": Decimal("96.0"), "feedback": "Excellent DP table structure!", "graded_by": lecturer, "graded_at": now - timedelta(days=19), "is_published": True})
    Grade.objects.update_or_create(assignment=cs400_a2, student=student, defaults={"score": Decimal("92.0"), "feedback": "Great work on Ford-Fulkerson min-cut proof.", "graded_by": lecturer, "graded_at": now - timedelta(days=9), "is_published": True})
    Grade.objects.update_or_create(assignment=cs400_a3, student=student, defaults={"score": Decimal("98.0"), "feedback": "Near-optimal TSP approximation!", "graded_by": lecturer, "graded_at": now - timedelta(days=1), "is_published": True})
    # CS400 weighted: (96*0.3 + 92*0.3 + 98*0.4) = 28.8 + 27.6 + 39.2 = 95.6% -> 'A' (4.00, 4 cr => 16.00 QP)

    # ── CS301 Assignments & Published Grades ──
    cs301_a1, _ = Assignment.objects.update_or_create(
        course=cs301, title="Lab 1: Multi-threaded Concurrency",
        defaults={"assignment_type": "lab", "max_score": 100, "weight": 30, "due_date": now - timedelta(days=22), "is_published": True, "created_by": lecturer}
    )
    cs301_a2, _ = Assignment.objects.update_or_create(
        course=cs301, title="Midterm: Deadlocks & Semaphores",
        defaults={"assignment_type": "exam", "max_score": 100, "weight": 40, "due_date": now - timedelta(days=12), "is_published": True, "created_by": lecturer}
    )
    cs301_a3, _ = Assignment.objects.update_or_create(
        course=cs301, title="Lab 2: Virtual Memory Paging",
        defaults={"assignment_type": "lab", "max_score": 100, "weight": 30, "due_date": now - timedelta(days=4), "is_published": True, "created_by": lecturer}
    )

    for a in [cs301_a1, cs301_a2, cs301_a3]:
        GradeBatch.objects.update_or_create(
            assignment=a,
            defaults={"status": GradeBatch.Status.PUBLISHED, "submitted_by": lecturer, "reviewed_by": staff, "published_at": now - timedelta(days=1)}
        )

    Grade.objects.update_or_create(assignment=cs301_a1, student=student, defaults={"score": Decimal("88.0"), "feedback": "Good thread synchronization.", "graded_by": lecturer, "graded_at": now - timedelta(days=21), "is_published": True})
    Grade.objects.update_or_create(assignment=cs301_a2, student=student, defaults={"score": Decimal("85.0"), "feedback": "Correct semaphore analysis.", "graded_by": lecturer, "graded_at": now - timedelta(days=11), "is_published": True})
    Grade.objects.update_or_create(assignment=cs301_a3, student=student, defaults={"score": Decimal("90.0"), "feedback": "Clean LRU cache implementation.", "graded_by": lecturer, "graded_at": now - timedelta(days=3), "is_published": True})
    # CS301 weighted: (88*0.3 + 85*0.4 + 90*0.3) = 26.4 + 34.0 + 27.0 = 87.4% -> 'B+' (3.30, 4 cr => 13.20 QP)

    # ── DS201 Assignments & Published Grades ──
    ds201_a1, _ = Assignment.objects.update_or_create(
        course=ds201, title="Project 1: Exploratory Data Analysis",
        defaults={"assignment_type": "project", "max_score": 100, "weight": 40, "due_date": now - timedelta(days=18), "is_published": True, "created_by": lecturer}
    )
    ds201_a2, _ = Assignment.objects.update_or_create(
        course=ds201, title="Project 2: Neural Network Classifier",
        defaults={"assignment_type": "project", "max_score": 100, "weight": 60, "due_date": now - timedelta(days=5), "is_published": True, "created_by": lecturer}
    )

    for a in [ds201_a1, ds201_a2]:
        GradeBatch.objects.update_or_create(
            assignment=a,
            defaults={"status": GradeBatch.Status.PUBLISHED, "submitted_by": lecturer, "reviewed_by": staff, "published_at": now - timedelta(days=1)}
        )

    Grade.objects.update_or_create(assignment=ds201_a1, student=student, defaults={"score": Decimal("94.0"), "feedback": "Detailed outlier treatment.", "graded_by": lecturer, "graded_at": now - timedelta(days=17), "is_published": True})
    Grade.objects.update_or_create(assignment=ds201_a2, student=student, defaults={"score": Decimal("91.0"), "feedback": "Good loss convergence curve.", "graded_by": lecturer, "graded_at": now - timedelta(days=4), "is_published": True})
    # DS201 weighted: (94*0.4 + 91*0.6) = 37.6 + 54.6 = 92.2% -> 'A-' (3.70, 3 cr => 11.10 QP)

    # ── MATH205 Assignments & Published Grades ──
    math205_a1, _ = Assignment.objects.update_or_create(
        course=math205, title="Midterm: Matrix Decompositions & SVD",
        defaults={"assignment_type": "exam", "max_score": 100, "weight": 50, "due_date": now - timedelta(days=15), "is_published": True, "created_by": lecturer}
    )
    math205_a2, _ = Assignment.objects.update_or_create(
        course=math205, title="Final: Eigenvalues & Vector Spaces",
        defaults={"assignment_type": "exam", "max_score": 100, "weight": 50, "due_date": now - timedelta(days=3), "is_published": True, "created_by": lecturer}
    )

    for a in [math205_a1, math205_a2]:
        GradeBatch.objects.update_or_create(
            assignment=a,
            defaults={"status": GradeBatch.Status.PUBLISHED, "submitted_by": lecturer, "reviewed_by": staff, "published_at": now - timedelta(days=1)}
        )

    Grade.objects.update_or_create(assignment=math205_a1, student=student, defaults={"score": Decimal("95.0"), "feedback": "Accurate SVD calculation.", "graded_by": lecturer, "graded_at": now - timedelta(days=14), "is_published": True})
    Grade.objects.update_or_create(assignment=math205_a2, student=student, defaults={"score": Decimal("89.0"), "feedback": "Good understanding of eigenspaces.", "graded_by": lecturer, "graded_at": now - timedelta(days=2), "is_published": True})
    # MATH205 weighted: (95*0.5 + 89*0.5) = 47.5 + 44.5 = 92.0% -> 'A-' (3.70, 3 cr => 11.10 QP)

    # Submissions
    Submission.objects.update_or_create(
        assignment=cs400_a1, student=student,
        defaults={"text_content": "https://github.com/alex-mercer/dp-solver\nOptimal DP algorithm.", "status": Submission.Status.GRADED, "submitted_at": now - timedelta(days=21)}
    )
    Submission.objects.update_or_create(
        assignment=cs301_a1, student=student,
        defaults={"text_content": "https://github.com/alex-mercer/os-sync\nPOSIX semaphores and mutexes.", "status": Submission.Status.GRADED, "submitted_at": now - timedelta(days=23)}
    )

    # ── 8. HISTORICAL TRANSCRIPTS & RECOMPUTE ALL GPAS ────────────────────────
    print("8. Creating Historical Transcripts and GPA Records...")
    # Spring 2024 (Semester 1)
    Transcript.objects.update_or_create(
        student=student, course=cs101, semester="2024-SPRING",
        defaults={"semester_label": "Spring 2024", "score_percentage": Decimal("94.50"), "final_grade": "A", "grade_points": Decimal("4.00"), "credits_attempted": 4, "credits_earned": 4, "quality_points": Decimal("16.00")}
    )
    Transcript.objects.update_or_create(
        student=student, course=math101, semester="2024-SPRING",
        defaults={"semester_label": "Spring 2024", "score_percentage": Decimal("91.00"), "final_grade": "A-", "grade_points": Decimal("3.70"), "credits_attempted": 4, "credits_earned": 4, "quality_points": Decimal("14.80")}
    )
    Transcript.objects.update_or_create(
        student=student, course=eng101, semester="2024-SPRING",
        defaults={"semester_label": "Spring 2024", "score_percentage": Decimal("96.00"), "final_grade": "A", "grade_points": Decimal("4.00"), "credits_attempted": 3, "credits_earned": 3, "quality_points": Decimal("12.00")}
    )

    # Fall 2024 (Semester 2)
    Transcript.objects.update_or_create(
        student=student, course=cs201, semester="2024-FALL",
        defaults={"semester_label": "Fall 2024", "score_percentage": Decimal("95.00"), "final_grade": "A", "grade_points": Decimal("4.00"), "credits_attempted": 4, "credits_earned": 4, "quality_points": Decimal("16.00")}
    )
    Transcript.objects.update_or_create(
        student=student, course=math102, semester="2024-FALL",
        defaults={"semester_label": "Fall 2024", "score_percentage": Decimal("86.50"), "final_grade": "B+", "grade_points": Decimal("3.30"), "credits_attempted": 4, "credits_earned": 4, "quality_points": Decimal("13.20")}
    )
    Transcript.objects.update_or_create(
        student=student, course=phy101, semester="2024-FALL",
        defaults={"semester_label": "Fall 2024", "score_percentage": Decimal("92.00"), "final_grade": "A-", "grade_points": Decimal("3.70"), "credits_attempted": 4, "credits_earned": 4, "quality_points": Decimal("14.80")}
    )

    # 2025-SPRING (Current Semester Transcript Rows)
    Transcript.objects.update_or_create(
        student=student, course=cs400, semester="2025-SPRING",
        defaults={"semester_label": "Spring 2025", "score_percentage": Decimal("95.60"), "final_grade": "A", "grade_points": Decimal("4.00"), "credits_attempted": 4, "credits_earned": 4, "quality_points": Decimal("16.00")}
    )
    Transcript.objects.update_or_create(
        student=student, course=cs301, semester="2025-SPRING",
        defaults={"semester_label": "Spring 2025", "score_percentage": Decimal("87.40"), "final_grade": "B+", "grade_points": Decimal("3.30"), "credits_attempted": 4, "credits_earned": 4, "quality_points": Decimal("13.20")}
    )
    Transcript.objects.update_or_create(
        student=student, course=ds201, semester="2025-SPRING",
        defaults={"semester_label": "Spring 2025", "score_percentage": Decimal("92.20"), "final_grade": "A-", "grade_points": Decimal("3.70"), "credits_attempted": 3, "credits_earned": 3, "quality_points": Decimal("11.10")}
    )
    Transcript.objects.update_or_create(
        student=student, course=math205, semester="2025-SPRING",
        defaults={"semester_label": "Spring 2025", "score_percentage": Decimal("92.00"), "final_grade": "A-", "grade_points": Decimal("3.70"), "credits_attempted": 3, "credits_earned": 3, "quality_points": Decimal("11.10")}
    )

    # ── 9. RUN GPA ENGINE TO COMPUTE EXACT TERM AND CUMULATIVE STATS ─────────
    from apps.grades.gpa import recompute_student_gpas
    recompute_student_gpas(student, "2024-SPRING", "Spring 2024")
    recompute_student_gpas(student, "2024-FALL", "Fall 2024")
    res_curr = recompute_student_gpas(student, "2025-SPRING", "Spring 2025")

    # Clear Django cache
    from django.core.cache import cache
    cache.clear()

    print("\n" + "="*70)
    print("✅ DATABASE SEED COMPLETE! All test data populated successfully.")
    print("="*70)
    print(f"Calculated Student GPA:")
    print(f"  • Spring 2024 Semester GPA: 3.89  (11 Credits)")
    print(f"  • Fall 2024 Semester GPA:   3.67  (12 Credits)")
    print(f"  • Spring 2025 Semester GPA: {res_curr['semester_gpa']}  (14 Credits)")
    print(f"  • Total Cumulative GPA:     {res_curr['cumulative_gpa']}  (37 Total Credits)")
    print("="*70)
    print("Demo User Logins for all 6 Institutional Roles (Password: 'password123' for all):")
    print("  • Super Admin:          admin@uniportal.edu    (Alice Admin)")
    print("  • Academic Officer:     academic@uniportal.edu (Sarah Connor)")
    print("  • Head of Department:   hod@uniportal.edu      (Dr. Margaret Hamilton)")
    print("  • Finance Officer:      finance@uniportal.edu  (Marcus Thorne)")
    print("  • Lecturer:             lecturer@uniportal.edu (Dr. Alan Turing)")
    print("  • Student:              student@uniportal.edu  (Alex Mercer, ID: STU-2024-8891)")
    print("="*70)

if __name__ == "__main__":
    seed()
