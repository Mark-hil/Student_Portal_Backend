import os
import django
from datetime import timedelta

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings.development')
django.setup()

from django.contrib.auth import get_user_model
from apps.courses.models import Course, Category, Enrollment
from django.utils import timezone

User = get_user_model()

print("🚀 Starting Database Seed...")

print("1. Creating Users...")
admin, _ = User.objects.get_or_create(
    email="admin@uniportal.edu", 
    defaults={"first_name": "Alice", "last_name": "Admin", "role": "admin", "is_staff": True, "is_superuser": True}
)
admin.set_password("password123")
admin.save()

instructor, _ = User.objects.get_or_create(
    email="lecturer@uniportal.edu", 
    defaults={"first_name": "Dr. Bob", "last_name": "Lecturer", "role": "instructor"}
)
instructor.set_password("password123")
instructor.save()

student, _ = User.objects.get_or_create(
    email="student@uniportal.edu", 
    defaults={"first_name": "Charlie", "last_name": "Student", "role": "student"}
)
student.set_password("password123")
student.save()

print("2. Creating Course Category...")
cat, _ = Category.objects.get_or_create(name="Computer Science", slug="computer-science")

print("3. Creating Course...")
course, _ = Course.objects.get_or_create(
    code="CS400",
    slug="cs400-advanced-algorithms",
    defaults={
        "title": "Advanced Algorithms",
        "description": "A comprehensive deep dive into algorithm analysis, dynamic programming, and graph theory.",
        "category": cat,
        "credits": 4,
        "max_students": 50,
        "semester": "FA24",
        "status": "active",
        "start_date": timezone.now().date(),
        "end_date": (timezone.now() + timedelta(days=90)).date()
    }
)

print("4. Assigning Lecturer to Course...")
course.instructors.add(instructor)

print("5. Enrolling Student in Course...")
Enrollment.objects.get_or_create(
    student=student,
    course=course,
    defaults={"status": "active", "enrolled_at": timezone.now()}
)

print("\n✅ Seed Complete! Here are your test accounts (Password for all is 'password123'):")
print("   - Admin:      admin@uniportal.edu")
print("   - Lecturer:   lecturer@uniportal.edu")
print("   - Student:    student@uniportal.edu")
