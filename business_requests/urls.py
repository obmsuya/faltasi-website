from django.urls import path

from . import views

app_name = "business_requests"

urlpatterns = [
    # Business registration
    path("register/", views.business_register, name="business_register"),

    # Business profile
    path("profile/", views.business_profile, name="business_profile"),
    path("whatsapp-ai-settings/", views.whatsapp_ai_settings, name="whatsapp_ai_settings"),

    # Departments
    path("departments/", views.department_management, name="department_management"),
    path("departments/add/", views.department_add, name="department_add"),
    path("departments/<int:department_id>/edit/", views.department_edit, name="department_edit"),
    path("departments/<int:department_id>/toggle/", views.department_toggle, name="department_toggle"),

    # Staff management
    path("staff/", views.staff_management, name="staff_management"),
    path("staff/add/", views.add_department_member, name="add_department_member"),
    path("staff/<int:user_id>/edit/", views.edit_user, name="edit_user"),
    path("staff/<int:user_id>/status/", views.toggle_user_status, name="toggle_user_status"),

    # Business requests
    path("", views.request_dashboard, name="dashboard"),
    path("<int:request_id>/assign/", views.assign_request, name="assign_request"),
    path("<int:request_id>/", views.request_detail, name="request_detail"),
    path("my-requests/", views.my_requests, name="my_requests"),
    path("<int:request_id>/update/", views.update_request, name="update_request"),
    path("<int:request_id>/send-whatsapp/", views.send_request_whatsapp_message, name="send_request_whatsapp_message"),
    path("admin-upload-category-questions/", views.upload_category_questions, name="upload_category_questions"),
    path("requests/<int:request_id>/set-department/", views.set_request_department, name="set_request_department"),

    # Dashboards and platform administration
    path("dashboard/", views.business_dashboard, name="business_dashboard"),
    path("platform-dashboard/", views.platform_dashboard, name="platform_dashboard"),
    path("switch-organization/", views.switch_organization, name="switch_organization"),
    path("organizations/", views.organization_management, name="organization_management"),
    path("organization-owners/", views.organization_owners, name="organization_owners"),
    path("organizations/create/", views.organization_create, name="organization_create"),
    path("organizations/<int:organization_id>/create-owner/", views.organization_create_owner, name="organization_create_owner"),
    path("organizations/<int:organization_id>/status/", views.organization_toggle_status, name="organization_toggle_status"),
    path("gis-map/", views.gis_map, name="gis_map"),
    path("gis-map/data/", views.gis_map_data, name="gis_map_data"),
    path(
        "gis-map/create/",
        views.gis_create_location,
        name="gis_create_location",
    ),
    path(
        "gis-map/update/<uuid:reference>/",
        views.gis_update_location,
        name="gis_update_location",
    ),
    path(
        "gis-map/review/<uuid:reference>/",
        views.gis_review_location,
        name="gis_review_location",
    ),

    path(
        "gis-map/delete/<uuid:reference>/",
        views.gis_delete_location,
        name="gis_delete_location",
    ),

    path(
        "gis-map/history/<uuid:reference>/",
        views.gis_location_history,
        name="gis_location_history",
    ),

    path(
        "gis-map/export/csv/",
        views.gis_export_csv,
        name="gis_export_csv",
    ),
]
