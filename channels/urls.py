from django.urls import path
from . import views

app_name = "channels"
urlpatterns = [
    path("", views.channel_dashboard, name="dashboard"),
    path("products/<int:product_id>/<str:channel>/toggle/", views.toggle_product_channel, name="toggle_product_channel"),
]
