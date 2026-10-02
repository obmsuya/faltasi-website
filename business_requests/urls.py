from django.urls import path

from . import views


app_name = "business_requests"


urlpatterns = [

    # =========================================================
    # BUSINESS REGISTRATION
    # =========================================================

    path(
        "register/",
        views.business_register,
        name="business_register",
    ),


    # =========================================================
    # BUSINESS DASHBOARD
    # =========================================================

    path(
        "dashboard/",
        views.business_dashboard,
        name="business_dashboard",
    ),


    # =========================================================
    # BUSINESS PROFILE
    # =========================================================

    path(
        "profile/",
        views.business_profile,
        name="business_profile",
    ),


    # =========================================================
    # DEPARTMENTS
    # =========================================================

    path(
        "departments/",
        views.department_management,
        name="department_management",
    ),

    path(
        "departments/add/",
        views.department_add,
        name="department_add",
    ),

    path(
        "departments/<int:department_id>/edit/",
        views.department_edit,
        name="department_edit",
    ),

    path(
        "departments/<int:department_id>/toggle/",
        views.department_toggle,
        name="department_toggle",
    ),


    # =========================================================
    # STAFF MANAGEMENT
    # =========================================================

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


    # =========================================================
    # BUSINESS REQUESTS
    # =========================================================

    path(
        "",
        views.request_dashboard,
        name="dashboard",
    ),

    path(
        "<int:request_id>/assign/",
        views.assign_request,
        name="assign_request",
    ),

    path(
        "<int:request_id>/",
        views.request_detail,
        name="request_detail",
    ),

    path(
        "my-requests/",
        views.my_requests,
        name="my_requests",
    ),
    path(
        "<int:request_id>/update/",
        views.update_request,
        name="update_request",
    ),

    path(
        "<int:request_id>/send-whatsapp/",
        views.send_request_whatsapp_message,
        name="send_request_whatsapp_message",
    ),

    path(
        "admin-upload-category-questions/",
        views.upload_category_questions,
        name="upload_category_questions",
    ),

    path(
        "admin-upload-category-questions/",
        views.upload_category_questions,
        name="upload_category_questions",
    ),

    

    
]