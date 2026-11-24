from django.urls import include, path
from rest_framework.routers import DefaultRouter

from . import views

router = DefaultRouter()
router.register("customers", views.RecordViewSet, basename="customer")

urlpatterns = [
    path("auth/token/", views.ThrottledObtainAuthToken.as_view(), name="api-token"),
    path("auth/token/revoke/", views.RevokeTokenView.as_view(), name="api-token-revoke"),
    path("me/", views.MeView.as_view(), name="api-me"),
    path("", include(router.urls)),
]