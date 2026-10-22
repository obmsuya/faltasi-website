
from django.urls import path
from . import views

app_name = "products"

urlpatterns = [
    path("", views.product_list, name="product_list"),
    path("add/", views.product_create, name="product_create"),
    path("<int:product_id>/edit/", views.product_edit, name="product_edit"),
    path("<int:product_id>/toggle/", views.product_toggle_status, name="product_toggle_status"),
    path("<int:product_id>/share-whatsapp/", views.product_share_whatsapp, name="product_share_whatsapp"),
    path(
        "<int:product_id>/share-whatsapp/",
        views.product_share_whatsapp,
        name="product_share_whatsapp",
    ),
]
