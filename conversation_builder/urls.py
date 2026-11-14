from django.urls import path

from . import views

app_name = "conversation_builder"

urlpatterns = [
    path("", views.overview, name="overview"),
    path(
        "create/",
        views.create_configuration_view,
        name="create_configuration",
    ),
    path(
        "draft/create/",
        views.create_draft_view,
        name="create_draft",
    ),
    path(
        "publish/",
        views.publish_draft_view,
        name="publish_draft",
    ),
    path(
        "products/",
        views.product_conversations,
        name="product_conversations",
    ),
    path(
        "products/create/",
        views.create_product_configuration_view,
        name="create_product_configuration",
    ),

    path(
        "products/<int:configuration_id>/edit/",
        views.edit_product_configuration_view,
        name="edit_product_configuration",
    ),

    path(
        "products/<int:configuration_id>/draft/create/",
        views.create_product_draft_view,
        name="create_product_draft",
    ),


    path(
        "products/<int:configuration_id>/publish/",
        views.publish_product_draft_view,
        name="publish_product_draft",
    ),
]