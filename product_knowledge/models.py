
import os
import uuid

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import FileExtensionValidator
from django.db import models
from django.db.models import Q
from django.utils import timezone


# ---------------------------------------------------------
# CONFIGURATION
# ---------------------------------------------------------

MAX_DOCUMENT_SIZE = 50 * 1024 * 1024  # 50 MB per file

ALLOWED_DOCUMENT_EXTENSIONS = [
      "pdf",
    "docx",
    "xlsx",
    "csv",
    "txt",
    "md",
]


def validate_document_size(file):
    """Reject documents larger than the configured limit."""
    if file and file.size > MAX_DOCUMENT_SIZE:
        raise ValidationError(
            "The maximum permitted document size is 50 MB."
        )


def validate_document_extension(file):
    """Validate the filename extension."""
    if not file:
        return

    extension = os.path.splitext(file.name)[1].lower().lstrip(".")

    if extension not in ALLOWED_DOCUMENT_EXTENSIONS:
        raise ValidationError(
            "Unsupported document type. Allowed types: "
            + ", ".join(ALLOWED_DOCUMENT_EXTENSIONS)
        )



def validate_document_content(file):
    """
    Perform a lightweight content check against the file extension.

    This is a first-line check only. DOCX and XLSX both use ZIP containers,
    so their internal structure must still be validated by the document parser.
    """
    if not file:
        return

    extension = os.path.splitext(file.name)[1].lower()
    original_position = None

    try:
        if hasattr(file, "tell"):
            original_position = file.tell()
        if hasattr(file, "seek"):
            file.seek(0)
        header = file.read(8192)
    except (OSError, ValueError, AttributeError) as exc:
        raise ValidationError(
            "The uploaded file could not be inspected safely."
        ) from exc
    finally:
        if original_position is not None and hasattr(file, "seek"):
            try:
                file.seek(original_position)
            except (OSError, ValueError):
                pass

    if isinstance(header, str):
        header = header.encode("utf-8", errors="ignore")

    if extension == ".pdf":
        valid = header.lstrip().startswith(b"%PDF-")
    elif extension in {".docx", ".xlsx"}:
        valid = header.startswith(b"PK\\x03\\x04")
    elif extension in {".csv", ".txt", ".md"}:
        valid = b"\\x00" not in header
    else:
        valid = False

    if not valid:
        raise ValidationError(
            "The file content does not match its declared file type."
        )
def document_upload_path(instance, filename):
    """Organize uploads by organization and document ID."""
    extension = os.path.splitext(filename)[1].lower()

    return (
        f"product_knowledge/"
        f"organization_{instance.organization_id}/"
        f"{instance.id or uuid.uuid4()}/"
        f"source{extension}"
    )


# ---------------------------------------------------------
# PRODUCT KNOWLEDGE DOCUMENT
# ---------------------------------------------------------

class ProductKnowledgeDocument(models.Model):

    class DocumentType(models.TextChoices):
        PRODUCT_CATALOGUE = "catalogue", "Product Catalogue"
        PRODUCT_MANUAL = "manual", "Product Manual"
        TECHNICAL_SPEC = "technical", "Technical Specification"
        PRICE_LIST = "price_list", "Price List"
        FAQ = "faq", "Frequently Asked Questions"
        POLICY = "policy", "Policy or Procedure"
        TRAINING = "training", "Training Material"
        GENERAL = "general", "General Knowledge"
        OTHER = "other", "Other"

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        PROCESSING = "processing", "Processing"
        READY = "ready", "Ready"
        FAILED = "failed", "Failed"
        ARCHIVED = "archived", "Archived"

    class IndexStatus(models.TextChoices):
        NOT_INDEXED = "not_indexed", "Not Indexed"
        PENDING = "pending", "Indexing Pending"
        INDEXING = "indexing", "Indexing"
        INDEXED = "indexed", "Indexed"
        FAILED = "failed", "Indexing Failed"

    # Tenant / ownership
    organization = models.ForeignKey(
        "organizations.Organization",
        on_delete=models.CASCADE,
        related_name="product_knowledge_documents",
        db_index=True,
    )

    # Optional link to a product in the existing product database.
    # A document can also cover an entire catalogue or several products.
    product = models.ForeignKey(
        "products.Product",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="knowledge_documents",
    )

    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="uploaded_knowledge_documents",
    )

    # Document identity and description
    title = models.CharField(max_length=255)
    description = models.TextField(blank=True)

    document_type = models.CharField(
        max_length=30,
        choices=DocumentType.choices,
        default=DocumentType.GENERAL,
        db_index=True,
    )

    # File storage
    file = models.FileField(
        upload_to=document_upload_path,
        validators=[
            FileExtensionValidator(
                allowed_extensions=ALLOWED_DOCUMENT_EXTENSIONS
            ),
            validate_document_size,
            validate_document_extension,
            validate_document_content,
        ],
    )

    original_filename = models.CharField(
        max_length=255,
        blank=True,
    )

    file_extension = models.CharField(
        max_length=10,
        blank=True,
    )

    mime_type = models.CharField(
        max_length=150,
        blank=True,
    )

    file_size_bytes = models.PositiveBigIntegerField(
        default=0,
    )

    # Calculate this in the upload/processing service.
    # It supports duplicate detection without loading file content
    # into the database.
    sha256 = models.CharField(
        max_length=64,
        blank=True,
        db_index=True,
    )

    # Extraction and processing
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING,
        db_index=True,
    )

    index_status = models.CharField(
        max_length=20,
        choices=IndexStatus.choices,
        default=IndexStatus.NOT_INDEXED,
        db_index=True,
    )

    processing_attempts = models.PositiveSmallIntegerField(
        default=0,
    )

    processing_started_at = models.DateTimeField(
        null=True,
        blank=True,
    )

    processing_completed_at = models.DateTimeField(
        null=True,
        blank=True,
    )

    processing_error = models.TextField(blank=True)
    index_error = models.TextField(blank=True)

    # Extracted text can be useful for inspection and troubleshooting.
    # Searchable chunks are stored separately below.
    extracted_text = models.TextField(blank=True)

    page_count = models.PositiveIntegerField(
        null=True,
        blank=True,
    )

    chunk_count = models.PositiveIntegerField(default=0)

    language = models.CharField(
        max_length=20,
        blank=True,
    )

    # External AI provider references.
    # These are identifiers only, never API keys.
    ai_provider = models.CharField(
        max_length=50,
        blank=True,
    )

    ai_file_id = models.CharField(
        max_length=255,
        blank=True,
    )

    ai_vector_store_id = models.CharField(
        max_length=255,
        blank=True,
    )

    # Extensible data for parser versions, source details,
    # processing configuration and other non-secret metadata.
    metadata = models.JSONField(default=dict, blank=True)

    # Publication and lifecycle
    is_active = models.BooleanField(
        default=True,
        db_index=True,
    )

    deleted_at = models.DateTimeField(
        null=True,
        blank=True,
    )

    uploaded_at = models.DateTimeField(
        auto_now_add=True,
        db_index=True,
    )

    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-uploaded_at"]
        indexes = [
            models.Index(
                fields=["organization", "status"],
                name="pkdoc_org_status_idx",
            ),
            models.Index(
                fields=["organization", "document_type"],
                name="pkdoc_org_type_idx",
            ),
            models.Index(
                fields=["organization", "is_active", "deleted_at"],
                name="pkdoc_org_active_idx",
            ),
            models.Index(
                fields=["organization", "index_status"],
                name="pkdoc_org_index_idx",
            ),
        ]
        constraints = [
            models.CheckConstraint(
                condition=Q(file_size_bytes__gte=0),
                name="pkdoc_size_nonnegative",
            ),
        ]

    def clean(self):
        super().clean()

        # Prevent accidentally linking a product from another tenant.
        if self.product_id and self.organization_id:
            product_org_id = (
                type(self.product)
                .objects.filter(pk=self.product_id)
                .values_list("organization_id", flat=True)
                .first()
            )

            if product_org_id != self.organization_id:
                raise ValidationError({
                    "product": (
                        "The selected product must belong to "
                        "the same organization as this document."
                    )
                })

        if self.file:
            validate_document_size(self.file)
            validate_document_extension(self.file)
            # Avoid reopening an already-stored remote file on every save.
            # Validate content when Django has an uploaded, uncommitted file.
            if getattr(self.file, "_committed", True) is False:
                validate_document_content(self.file)

    def save(self, *args, **kwargs):
        # Keep filename metadata consistent without opening the file.
        if self.file:
            name = os.path.basename(self.file.name)

            if not self.original_filename:
                self.original_filename = name[:255]

            self.file_extension = (
                os.path.splitext(name)[1].lower().lstrip(".")[:10]
            )

            try:
                self.file_size_bytes = self.file.size
            except (OSError, ValueError):
                pass

        # Enforce tenant validation even when save() is called directly.
        # Database constraints alone cannot enforce this cross-table rule.
        self.clean()

        super().save(*args, **kwargs)

    @property
    def is_deleted(self):
        return self.deleted_at is not None

    def archive(self):
        self.status = self.Status.ARCHIVED
        self.is_active = False
        self.save(update_fields=[
            "status",
            "is_active",
            "updated_at",
        ])

    def soft_delete(self):
        self.deleted_at = timezone.now()
        self.is_active = False
        self.save(update_fields=[
            "deleted_at",
            "is_active",
            "updated_at",
        ])

    def __str__(self):
        return f"{self.title} (Organization {self.organization_id})"


# ---------------------------------------------------------
# SEARCHABLE DOCUMENT CHUNKS
# ---------------------------------------------------------

class ProductKnowledgeChunk(models.Model):
    """
    A document is divided into smaller passages for retrieval.

    Chunk creation, embeddings and AI indexing are handled by
    processing services, not automatically by this model.
    """

    document = models.ForeignKey(
        ProductKnowledgeDocument,
        on_delete=models.CASCADE,
        related_name="chunks",
    )

    organization = models.ForeignKey(
        "organizations.Organization",
        on_delete=models.CASCADE,
        related_name="product_knowledge_chunks",
        db_index=True,
    )

    chunk_index = models.PositiveIntegerField()

    text = models.TextField()

    # Optional source location within the original document.
    page_number = models.PositiveIntegerField(
        null=True,
        blank=True,
    )

    section_title = models.CharField(
        max_length=255,
        blank=True,
    )

    token_count = models.PositiveIntegerField(
        default=0,
    )

    # Calculate from normalized chunk text in the processing service.
    content_hash = models.CharField(
        max_length=64,
        blank=True,
    )

    # Embedding and retrieval provider identifiers.
    embedding_model = models.CharField(
        max_length=100,
        blank=True,
    )

    external_vector_id = models.CharField(
        max_length=255,
        blank=True,
    )

    metadata = models.JSONField(default=dict, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["document_id", "chunk_index"]
        constraints = [
            models.UniqueConstraint(
                fields=["document", "chunk_index"],
                name="pkchunk_doc_index_unique",
            ),
        ]
        indexes = [
            models.Index(
                fields=["organization", "document"],
                name="pkchunk_org_doc_idx",
            ),
            models.Index(
                fields=["document", "page_number"],
                name="pkchunk_doc_page_idx",
            ),
            models.Index(
                fields=["content_hash"],
                name="pkchunk_hash_idx",
            ),
        ]

    def clean(self):
        super().clean()

        if (
            self.document_id
            and self.organization_id
            and self.document.organization_id != self.organization_id
        ):
            raise ValidationError(
                "A chunk and its document must belong to the same organization."
            )

        if not self.text or not self.text.strip():
            raise ValidationError({
                "text": "A knowledge chunk cannot be empty."
            })

    def save(self, *args, **kwargs):
        # Keep chunk ownership aligned with the parent document.
        if self.document_id:
            document_org_id = (
                ProductKnowledgeDocument.objects
                .filter(pk=self.document_id)
                .values_list("organization_id", flat=True)
                .first()
            )

            if document_org_id is not None:
                if self.organization_id and (
                    self.organization_id != document_org_id
                ):
                    raise ValidationError(
                        "Chunk organization must match its document."
                    )

                self.organization_id = document_org_id

        self.clean()
        super().save(*args, **kwargs)

    def __str__(self):
        return (
            f"Document {self.document_id} "
            f"- Chunk {self.chunk_index}"
        )
