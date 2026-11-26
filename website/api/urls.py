from django.urls import include, path
from rest_framework.routers import DefaultRouter

from . import views

router = DefaultRouter()
router.register("contacts", views.ContactViewSet, basename="contact")
router.register("companies", views.CompanyViewSet, basename="company")

urlpatterns = [
    path("auth/token/", views.ThrottledObtainAuthToken.as_view(), name="api-token"),
    path("auth/token/revoke/", views.RevokeTokenView.as_view(), name="api-token-revoke"),
    path("me/", views.MeView.as_view(), name="api-me"),
    path("verify/", views.VerifyView.as_view(), name="api-verify"),
    path("", include(router.urls)),
]