from django.urls import path
from . import views
app_name="organizations"
urlpatterns=[
 path("",views.organization_list,name="list"),
 path("add/",views.organization_create,name="create"),
 path("<int:pk>/",views.organization_detail,name="detail"),
 path("<int:pk>/edit/",views.organization_edit,name="edit"),
 path("<int:pk>/status/<str:status>/",views.organization_status,name="status"),
 path("<int:pk>/members/<int:member_id>/",views.member_action,name="member_action"),
 path("<int:pk>/delete/confirm/",views.organization_delete_confirm,name="delete_confirm"),
 path("<int:pk>/delete/",views.organization_delete,name="delete"),
]
