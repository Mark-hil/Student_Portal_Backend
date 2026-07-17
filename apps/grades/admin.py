"""Grades admin — covers the full 3-step result publication workflow."""
from django.contrib import admin
from django.utils.html import format_html
from .models import Assignment, Grade, GradeBatch, SemesterRecord, Transcript


class GradeInline(admin.TabularInline):
    model         = Grade
    extra         = 0
    raw_id_fields = ["student", "graded_by"]
    fields        = ["student", "score", "letter_grade_display", "feedback", "graded_at"]
    readonly_fields = ["letter_grade_display"]

    @admin.display(description="Letter")
    def letter_grade_display(self, obj):
        return obj.letter_grade


@admin.register(Assignment)
class AssignmentAdmin(admin.ModelAdmin):
    list_display   = ["title", "course", "assignment_type", "max_score", "weight", "due_date", "is_published", "batch_status"]
    list_filter    = ["assignment_type", "is_published", "course__semester"]
    search_fields  = ["title", "course__code"]
    raw_id_fields  = ["created_by"]
    inlines        = [GradeInline]

    @admin.display(description="Batch status")
    def batch_status(self, obj):
        try:
            return obj.grade_batch.get_status_display()
        except GradeBatch.DoesNotExist:
            return "—"


@admin.register(GradeBatch)
class GradeBatchAdmin(admin.ModelAdmin):
    list_display   = ["assignment", "status_badge", "submitted_by", "submitted_at", "reviewed_by", "published_at", "grade_count"]
    list_filter    = ["status"]
    search_fields  = ["assignment__title", "assignment__course__code", "submitted_by__email"]
    raw_id_fields  = ["submitted_by", "reviewed_by"]
    readonly_fields = ["submitted_at", "reviewed_at", "published_at"]
    actions        = ["action_approve", "action_publish"]

    @admin.display(description="Grade count")
    def grade_count(self, obj):
        return obj.assignment.grades.count()

    @admin.display(description="Status")
    def status_badge(self, obj):
        colours = {
            "draft":          "gray",
            "pending_review": "orange",
            "rejected":       "red",
            "approved":       "blue",
            "published":      "green",
        }
        c = colours.get(obj.status, "gray")
        return format_html(
            '<span style="background:{};color:#fff;padding:2px 8px;border-radius:99px;font-size:11px">{}</span>',
            c, obj.get_status_display()
        )

    @admin.action(description="Approve selected batches")
    def action_approve(self, request, queryset):
        for batch in queryset.filter(status=GradeBatch.Status.PENDING_REVIEW):
            try:
                batch.approve(request.user)
            except ValueError:
                pass

    @admin.action(description="Publish selected batches")
    def action_publish(self, request, queryset):
        for batch in queryset.filter(status__in=[GradeBatch.Status.APPROVED, GradeBatch.Status.PENDING_REVIEW]):
            try:
                batch.publish(request.user)
            except ValueError:
                pass


@admin.register(Grade)
class GradeAdmin(admin.ModelAdmin):
    list_display    = ["student", "assignment", "score", "letter_grade_display", "is_published_display", "graded_at"]
    list_filter     = ["assignment__assignment_type", "assignment__course__semester"]
    search_fields   = ["student__email", "assignment__title"]
    raw_id_fields   = ["student", "graded_by"]

    @admin.display(description="Letter")
    def letter_grade_display(self, obj):
        return obj.letter_grade

    @admin.display(boolean=True, description="Published")
    def is_published_display(self, obj):
        return obj.is_published


@admin.register(SemesterRecord)
class SemesterRecordAdmin(admin.ModelAdmin):
    list_display  = ["student", "semester_label", "semester_gpa", "cumulative_gpa", "semester_credits_attempted", "cumulative_credits_earned", "computed_at"]
    list_filter   = ["semester"]
    search_fields = ["student__email", "semester"]
    readonly_fields = [
        "semester_gpa", "cumulative_gpa",
        "semester_credits_attempted", "semester_credits_earned", "semester_quality_points",
        "cumulative_credits_attempted", "cumulative_credits_earned", "cumulative_quality_points",
        "computed_at",
    ]


@admin.register(Transcript)
class TranscriptAdmin(admin.ModelAdmin):
    list_display  = ["student", "course", "semester_label", "final_grade", "grade_points", "credits_attempted"]
    list_filter   = ["semester"]
    search_fields = ["student__email", "course__code"]
