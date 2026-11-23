from django.urls import path
from . import public_views

urlpatterns = [
    path("products/", public_views.public_product_list, name="products"),
    path("request-quote/", public_views.request_quote, name="request_quote"),
]
