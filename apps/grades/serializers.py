"""Grade serializers — full workflow: lecturer upload, officer review, student view."""
from rest_framework import serializers
from .models import Grade, GradeBatch, Assignment, SemesterRecord, Transcript


class AssignmentSerializer(serializers.ModelSerializer):
    course_code  = serializers.CharField(source="course.code",   read_only=True)
    course_title = serializers.CharField(source="course.title",  read_only=True)
    batch_id     = serializers.SerializerMethodField()

    class Meta:
        model  = Assignment
        fields = [
            "id", "title", "assignment_type", "max_score", "weight",
            "due_date", "is_published", "course_code", "course_title", "created_at",
            "batch_id"
        ]

    def get_batch_id(self, obj):
        return obj.grade_batch.id if hasattr(obj, 'grade_batch') else None


class AssignmentCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model  = Assignment
        fields = ["id", "course", "title", "assignment_type", "max_score", "weight", "due_date", "description"]

    def create(self, validated_data):
        validated_data["created_by"] = self.context["request"].user
        assignment = super().create(validated_data)
        GradeBatch.objects.create(assignment=assignment, status=GradeBatch.Status.DRAFT)
        return assignment


# ── Grade batch serializers ───────────────────────────────────────────────────

class BatchGradeEntrySerializer(serializers.Serializer):
    """Used when lecturer uploads individual scores."""
    student_id = serializers.CharField()
    score      = serializers.DecimalField(max_digits=6, decimal_places=2, min_value=0)
    feedback   = serializers.CharField(max_length=1000, required=False, allow_blank=True)


class GradeBatchListSerializer(serializers.ModelSerializer):
    assignment_title  = serializers.CharField(source="assignment.title",       read_only=True)
    course_code       = serializers.CharField(source="assignment.course.code", read_only=True)
    submitted_by_name = serializers.CharField(source="submitted_by.full_name", read_only=True, default="")
    grade_count       = serializers.IntegerField(read_only=True)

    class Meta:
        model  = GradeBatch
        fields = [
            "id", "assignment_title", "course_code", "status",
            "submitted_by_name", "submitted_at", "reviewed_at", "published_at",
            "grade_count",
        ]


class GradeEntrySerializer(serializers.ModelSerializer):
    student_name = serializers.CharField(source="student.full_name", read_only=True)
    student_code = serializers.CharField(source="student.student_id", read_only=True)
    letter_grade = serializers.CharField(read_only=True)
    percentage   = serializers.FloatField(read_only=True)

    class Meta:
        model  = Grade
        fields = [
            "id", "student_id", "student_name", "student_code",
            "score", "feedback", "letter_grade", "percentage",
        ]


class GradeBatchDetailSerializer(serializers.ModelSerializer):
    assignment      = AssignmentSerializer(read_only=True)
    submitted_by    = serializers.SerializerMethodField()
    reviewed_by     = serializers.SerializerMethodField()
    grades          = GradeEntrySerializer(source="assignment.grades", many=True, read_only=True)
    grade_count     = serializers.IntegerField(read_only=True)

    class Meta:
        model  = GradeBatch
        fields = [
            "id", "assignment", "status",
            "submitted_by", "submitted_at", "submission_note",
            "reviewed_by", "reviewed_at", "review_notes",
            "published_at", "grade_count", "grades",
        ]

    def get_submitted_by(self, obj):
        if obj.submitted_by:
            return {"id": str(obj.submitted_by.pk), "full_name": obj.submitted_by.full_name, "email": obj.submitted_by.email}
        return None

    def get_reviewed_by(self, obj):
        if obj.reviewed_by:
            return {"id": str(obj.reviewed_by.pk), "full_name": obj.reviewed_by.full_name, "email": obj.reviewed_by.email}
        return None


class SubmitBatchSerializer(serializers.Serializer):
    note = serializers.CharField(max_length=1000, required=False, allow_blank=True)


class RejectBatchSerializer(serializers.Serializer):
    notes = serializers.CharField(max_length=2000)


# ── Student grade view serializers ────────────────────────────────────────────

class GradeSerializer(serializers.ModelSerializer):
    assignment   = AssignmentSerializer(read_only=True)
    letter_grade = serializers.CharField(read_only=True)
    percentage   = serializers.FloatField(read_only=True)
    grade_points = serializers.DecimalField(max_digits=4, decimal_places=2, read_only=True)
    batch_status = serializers.CharField(read_only=True)

    class Meta:
        model  = Grade
        fields = [
            "id", "assignment", "score", "feedback",
            "letter_grade", "percentage", "grade_points",
            "batch_status", "graded_at",
        ]


class TranscriptRowSerializer(serializers.ModelSerializer):
    course_code  = serializers.CharField(source="course.code",    read_only=True)
    course_title = serializers.CharField(source="course.title",   read_only=True)
    credits      = serializers.IntegerField(source="course.credits", read_only=True)

    class Meta:
        model  = Transcript
        fields = [
            "id", "course_code", "course_title", "credits",
            "semester", "semester_label",
            "final_grade", "grade_points",
            "credits_attempted", "credits_earned", "quality_points",
        ]


class SemesterRecordSerializer(serializers.ModelSerializer):
    transcript_rows = serializers.SerializerMethodField()

    class Meta:
        model  = SemesterRecord
        fields = [
            "id", "semester", "semester_label", "status",
            "semester_gpa", "semester_credits_attempted", "semester_credits_earned", "semester_quality_points",
            "cumulative_gpa", "cumulative_credits_attempted", "cumulative_credits_earned", "cumulative_quality_points",
            "computed_at", "transcript_rows",
        ]

    def get_transcript_rows(self, obj):
        rows = Transcript.objects.filter(student=obj.student, semester=obj.semester).select_related("course")
        return TranscriptRowSerializer(rows, many=True).data
