

# Register your models here.
from django.contrib import admin
from .models import ProductCategory, Product


@admin.register(ProductCategory)
class ProductCategoryAdmin(admin.ModelAdmin):

    list_display = (
        "name",
        "is_active",
        "created_at",
        "updated_at",
    )

    list_filter = (
        "is_active",
        "created_at",
    )

    search_fields = (
        "name",
        "description",
    )

    ordering = (
        "-created_at",
    )


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):

    list_display = (
        "name",
        "category",
        "brand",
        "model",
        "price",
        "currency",
        "availability",
        "is_featured",
        "is_active",
        "created_at",
    )

    list_filter = (
        "category",
        "availability",
        "is_featured",
        "is_active",
        "currency",
        "created_at",
    )

    search_fields = (
        "name",
        "brand",
        "model",
        "sku",
        "description",
    )

    ordering = (
        "-created_at",
    )