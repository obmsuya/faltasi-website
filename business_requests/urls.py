from django.urls import path

from . import views


app_name = "business_requests"


urlpatterns = [
    path(
        "",
        views.request_dashboard,
        name="dashboard",
    ),

    path(
        "<int:request_id>/",
        views.request_detail,
        name="request_detail",
    ),

    path(
        "<int:request_id>/assign/",
        views.assign_request,
        name="assign_request",
    ),
    path(
    "staff/",
    views.staff_management,
    name="staff_management",
    ),

    path(
        "staff/add/",
        views.add_department_member,
        name="add_department_member",
    ),
    
]