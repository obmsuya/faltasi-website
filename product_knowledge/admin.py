
from django.contrib import admin

from .models import ProductKnowledgeDocument, ProductKnowledgeChunk


class ProductKnowledgeChunkInline(admin.TabularInline):
    model = ProductKnowledgeChunk
    extra = 0
    fields = (
        "chunk_index",
        "page_number",
        "section_title",
        "token_count",
    )
    readonly_fields = fields
    can_delete = False
    show_change_link = True


@admin.register(ProductKnowledgeDocument)
class ProductKnowledgeDocumentAdmin(admin.ModelAdmin):
    list_display = (
        "title",
        "organization",
        "document_type",
        "status",
        "index_status",
        "file_size_bytes",
        "uploaded_at",
    )

    list_filter = (
        "document_type",
        "status",
        "index_status",
        "is_active",
    )

    search_fields = (
        "title",
        "description",
        "original_filename",
        "sha256",
    )

    readonly_fields = (
        "original_filename",
        "file_extension",
        "mime_type",
        "file_size_bytes",
        "sha256",
        "processing_attempts",
        "processing_started_at",
        "processing_completed_at",
        "processing_error",
        "index_error",
        "page_count",
        "chunk_count",
        "ai_file_id",
        "ai_vector_store_id",
        "uploaded_at",
        "updated_at",
    )

    autocomplete_fields = ("product", "uploaded_by")
    inlines = (ProductKnowledgeChunkInline,)

    list_per_page = 25


@admin.register(ProductKnowledgeChunk)
class ProductKnowledgeChunkAdmin(admin.ModelAdmin):
    list_display = (
        "document",
        "organization",
        "chunk_index",
        "page_number",
        "token_count",
    )

    list_filter = ("embedding_model",)
    search_fields = ("text", "section_title")
    readonly_fields = ("created_at", "updated_at")
    list_per_page = 50
