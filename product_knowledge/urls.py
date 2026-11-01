
from django.urls import path

from . import views

app_name = "product_knowledge"

urlpatterns = [
    path("", views.document_list, name="document_list"),
    path("upload/", views.document_upload, name="document_upload"),
    path(
        "<int:document_id>/access/",
        views.document_update_access,
        name="document_update_access",
    ),
    path(
        "<int:document_id>/process/",
        views.document_process,
        name="document_process",
    ),
    path("ai/", views.ai_assistant, name="ai_assistant"),
]
