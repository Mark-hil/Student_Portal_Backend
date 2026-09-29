from rest_framework.routers import DefaultRouter
from .views import GradeViewSet, AssignmentViewSet, GradeBatchViewSet, GradeAppealViewSet

router = DefaultRouter()
router.register("assignments", AssignmentViewSet,  basename="assignment")
router.register("batches",     GradeBatchViewSet,   basename="grade-batch")
router.register("appeals",     GradeAppealViewSet,  basename="grade-appeal")
router.register("",            GradeViewSet,        basename="grade")

urlpatterns = router.urls
