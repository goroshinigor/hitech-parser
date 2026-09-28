from django.urls import path
from . import views

urlpatterns = [
    path("hello/",views.hello),
    path("parse/", views.parse_view, name="parse"),
]