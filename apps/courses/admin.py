from django.contrib import admin
from .models import Category, Course, CourseSchedule, Lesson, Enrollment, RegistrationWindow, LessonProgress


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ["name", "slug"]
    prepopulated_fields = {"slug": ("name",)}


class CourseScheduleInline(admin.TabularInline):
    model = CourseSchedule
    extra = 1


class LessonInline(admin.TabularInline):
    model = Lesson
    extra = 0
    ordering = ["order"]


@admin.register(Course)
class CourseAdmin(admin.ModelAdmin):
    list_display = ["code", "title", "status", "semester", "credits", "active_enrollment_count", "is_full"]
    list_filter = ["status", "semester", "category"]
    search_fields = ["code", "title"]
    prepopulated_fields = {"slug": ("title",)}
    filter_horizontal = ["instructors", "prerequisites"]
    inlines = [CourseScheduleInline, LessonInline]

    @admin.display(description="Enrolled")
    def active_enrollment_count(self, obj):
        return obj.active_enrollment_count

    @admin.display(boolean=True, description="Full")
    def is_full(self, obj):
        return obj.is_full


@admin.register(Enrollment)
class EnrollmentAdmin(admin.ModelAdmin):
    list_display = ["student", "course", "status", "enrolled_at", "progress_pct", "final_grade"]
    list_filter = ["status", "course__semester"]
    search_fields = ["student__email", "course__code"]
    raw_id_fields = ["student", "course"]


@admin.register(RegistrationWindow)
class RegistrationWindowAdmin(admin.ModelAdmin):
    list_display = ["semester", "opens_at", "closes_at", "is_active", "is_open"]

    @admin.display(boolean=True, description="Open now")
    def is_open(self, obj):
        return obj.is_open
