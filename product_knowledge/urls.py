
from django.urls import path

from . import views

app_name = "product_knowledge"

urlpatterns = [
    path("", views.document_list, name="document_list"),
    path("upload/", views.document_upload, name="document_upload"),
    path(
        "<int:document_id>/process/",
        views.document_process,
        name="document_process",
    ),
]
