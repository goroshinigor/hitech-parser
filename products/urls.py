from django.urls import path

from . import views

urlpatterns = [
    path("", views.index, name="index"),
    path("parse/", views.parse_product, name="parse"),
]