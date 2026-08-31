from django.urls import path
from main.views import sitemap
from django.contrib.sitemaps.views import sitemap
from main.sitemaps import StaticViewSitemap
from . import views


sitemaps = {
    "static": StaticViewSitemap,
}

urlpatterns = [
    path("", views.home, name="home"),
    path("about/", views.about, name="about"),
    path("services/", views.services, name="services"),
    path("contact/", views.contact, name="contact"),
    path("products/", views.products, name="products"),
    path('team/', views.team, name='team'),
    path(
        "sitemap.xml",
        sitemap,
        {"sitemaps": sitemaps},
        name="django_sitemap",
    ),
]