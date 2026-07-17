"""
Course serializers — complete version.
Includes registration, schedule, prereqs, and capacity data.
"""
from rest_framework import serializers
from django.db.models import Count, Q
from .models import Category, Course, CourseSchedule, Lesson, Enrollment, RegistrationWindow


class CategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = Category
        fields = ["id", "name", "slug", "icon"]


class CourseScheduleSerializer(serializers.ModelSerializer):
    day_name = serializers.CharField(source="get_day_of_week_display", read_only=True)

    class Meta:
        model = CourseSchedule
        fields = ["id", "day_of_week", "day_name", "start_time", "end_time", "room", "is_online", "meeting_link"]


class InstructorSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    full_name = serializers.CharField()
    email = serializers.EmailField()
    avatar = serializers.ImageField(allow_null=True)
    department = serializers.CharField()


class LessonSerializer(serializers.ModelSerializer):
    class Meta:
        model = Lesson
        fields = ["id", "title", "order", "lesson_type", "duration_minutes", "is_free_preview", "published_at"]


class PrerequisiteSerializer(serializers.ModelSerializer):
    class Meta:
        model = Course
        fields = ["id", "code", "title", "credits"]


class CourseListSerializer(serializers.ModelSerializer):
    """Lightweight — used in list/catalog views."""
    category = CategorySerializer(read_only=True)
    schedules = CourseScheduleSerializer(many=True, read_only=True)
    enrollment_count = serializers.IntegerField(source="active_enrollment_count", read_only=True)
    available_seats = serializers.IntegerField(read_only=True)
    is_full = serializers.BooleanField(read_only=True)
    is_enrolled = serializers.SerializerMethodField()
    enrollment_status = serializers.SerializerMethodField()
    prerequisites = PrerequisiteSerializer(many=True, read_only=True)
    instructors = InstructorSerializer(many=True, read_only=True)

    class Meta:
        model = Course
        fields = [
            "id", "code", "title", "slug", "description",
            "category", "credits", "status", "semester",
            "start_date", "end_date", "max_students",
            "enrollment_count", "available_seats", "is_full",
            "is_enrolled", "enrollment_status",
            "prerequisites", "schedules", "tags", "instructors",
        ]

    def get_is_enrolled(self, obj):
        request = self.context.get("request")
        if not request or not request.user.is_authenticated:
            return False
        return str(obj.id) in self.context.get("enrolled_ids", set())

    def get_enrollment_status(self, obj):
        """Return 'active'|'waitlisted'|'dropped'|None."""
        request = self.context.get("request")
        if not request or not request.user.is_authenticated:
            return None
        status_map = self.context.get("enrollment_status_map", {})
        return status_map.get(str(obj.id))


class CourseDetailSerializer(CourseListSerializer):
    """Full detail — includes lessons, instructors, prerequisites."""
    lessons = LessonSerializer(many=True, read_only=True)
    instructor_ids = serializers.ListField(child=serializers.UUIDField(), write_only=True, required=False)
    category_id = serializers.UUIDField(write_only=True, required=False)

    class Meta(CourseListSerializer.Meta):
        fields = CourseListSerializer.Meta.fields + ["lessons", "syllabus_url", "instructor_ids", "category_id"]

    def create(self, validated_data):
        instructor_ids = validated_data.pop("instructor_ids", [])
        category_id = validated_data.pop("category_id", None)
        if category_id:
            validated_data["category_id"] = category_id
        course = super().create(validated_data)
        if instructor_ids:
            course.instructors.set(instructor_ids)
        return course

    def update(self, instance, validated_data):
        instructor_ids = validated_data.pop("instructor_ids", None)
        category_id = validated_data.pop("category_id", None)
        if category_id:
            validated_data["category_id"] = category_id
        course = super().update(instance, validated_data)
        if instructor_ids is not None:
            course.instructors.set(instructor_ids)
        return course


# ── Enrollment ────────────────────────────────────────────────────────────────

class EnrollmentSerializer(serializers.ModelSerializer):
    course = CourseListSerializer(read_only=True)
    course_id = serializers.UUIDField(write_only=True)

    class Meta:
        model = Enrollment
        fields = [
            "id", "course", "course_id", "status",
            "enrolled_at", "progress_pct", "final_grade", "grade_points",
        ]
        read_only_fields = ["id", "enrolled_at", "status", "progress_pct", "final_grade", "grade_points"]

    def create(self, validated_data):
        from apps.courses.registration import RegistrationService, RegistrationError
        course_id = validated_data.pop("course_id")
        student = self.context["request"].user

        try:
            course = Course.objects.prefetch_related("prerequisites", "schedules").get(
                id=course_id, status=Course.Status.ACTIVE
            )
        except Course.DoesNotExist:
            raise serializers.ValidationError({"course_id": "Course not found or not active."})

        semester = course.semester or ""
        service = RegistrationService(student, semester)
        try:
            enrollment = service.register(course)
        except RegistrationError as e:
            raise serializers.ValidationError({e.code: e.detail})
        return enrollment


class BulkRegistrationSerializer(serializers.Serializer):
    """Accept a list of course IDs and register all atomically."""
    course_ids = serializers.ListField(
        child=serializers.UUIDField(),
        min_length=1,
        max_length=6,
    )

    def validate_course_ids(self, ids):
        courses = Course.objects.filter(id__in=ids, status=Course.Status.ACTIVE)
        found_ids = {str(c.id) for c in courses}
        missing = [str(i) for i in ids if str(i) not in found_ids]
        if missing:
            raise serializers.ValidationError(f"Courses not found or not active: {', '.join(missing)}")
        self._courses = list(courses)
        return ids

    def save(self, **kwargs):
        from apps.courses.registration import RegistrationService
        student = self.context["request"].user
        semester = self._courses[0].semester if self._courses else ""
        service = RegistrationService(student, semester)
        return service.bulk_register(self._courses)


class RegistrationWindowSerializer(serializers.ModelSerializer):
    is_open = serializers.BooleanField(read_only=True)

    class Meta:
        model = RegistrationWindow
        fields = ["id", "semester", "opens_at", "closes_at", "is_active", "is_open"]


class DropEnrollmentSerializer(serializers.Serializer):
    reason = serializers.CharField(max_length=500, required=False, allow_blank=True)
