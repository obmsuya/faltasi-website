from django.urls import path

from . import views


app_name = "customers"


urlpatterns = [

    path(
        "",
        views.customer_list,
        name="list",
    ),

    path(
        "add/",
        views.customer_create,
        name="create",
    ),

    path(
        "<int:customer_id>/",
        views.customer_detail,
        name="detail",
    ),

    path(
        "<int:customer_id>/edit/",
        views.customer_edit,
        name="edit",
    ),

    path(
        "<int:customer_id>/delete/",
        views.customer_delete,
        name="delete",
    ),
]