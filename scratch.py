import os
import django
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.development")
django.setup()

from apps.courses.models import Course
from apps.users.models import User
from apps.grades.models import Assignment

course = Course.objects.first()
lecturer = User.objects.filter(role='instructor').first()
assignment = Assignment.objects.create(
    course=course,
    title="Test Assignment",
    assignment_type="homework",
    created_by=lecturer
)
print("Assignment created:", assignment)
try:
    print("Grade Batch:", assignment.grade_batch)
except Exception as e:
    print("Error getting grade batch:", e)
