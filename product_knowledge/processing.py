
import hashlib
import logging
import tempfile

from pathlib import Path

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from .extractors import (
    DocumentExtractionError,
    extract_document_text,
)
from .models import (
    ProductKnowledgeDocument,
    ProductKnowledgeChunk,
)


logger = logging.getLogger(__name__)

# Character-based chunking configuration.
CHUNK_SIZE = 2500
CHUNK_OVERLAP = 300
MAX_DOCUMENT_SIZE = 50 * 1024 * 1024


def split_text_into_chunks(text):
    """
    Split extracted text into overlapping passages.
    Prefer paragraph or sentence boundaries where practical.
    """
    text = text.strip()

    if not text:
        return []

    chunks = []
    start = 0
    text_length = len(text)

    while start < text_length:
        end = min(start + CHUNK_SIZE, text_length)

        if end < text_length:
            boundary = text.rfind(
                "\n",
                start + CHUNK_SIZE // 2,
                end,
            )

            if boundary == -1:
                boundary = text.rfind(
                    ". ",
                    start + CHUNK_SIZE // 2,
                    end,
                )

            if boundary != -1:
                end = boundary + 1

        chunk_text = text[start:end].strip()

        if chunk_text:
            chunks.append(chunk_text)

        if end >= text_length:
            break

        next_start = max(0, end - CHUNK_OVERLAP)
        start = max(next_start, start + 1)

    return chunks


def _extract_from_storage(document):
    """
    Copy a Django storage file into a temporary directory.

    The temporary file is closed before the parser opens it.
    This avoids Windows file-permission errors and supports
    remote storage such as Cloudflare R2.
    """
    if not document.file:
        raise DocumentExtractionError(
            "No file is attached to this document."
        )

    if document.file.size > MAX_DOCUMENT_SIZE:
        raise DocumentExtractionError(
            "The document exceeds the 50 MB processing limit."
        )

    suffix = Path(document.file.name).suffix

    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir) / f"source{suffix}"
        total_bytes = 0

        with document.file.open("rb") as source:
            with temp_path.open("wb") as destination:
                while True:
                    data = source.read(1024 * 1024)

                    if not data:
                        break

                    total_bytes += len(data)

                    if total_bytes > MAX_DOCUMENT_SIZE:
                        raise DocumentExtractionError(
                            "The document exceeds the 50 MB processing limit."
                        )

                    destination.write(data)

        # The file is now closed, so Windows parsers can open it.
        return extract_document_text(temp_path)


def process_document(document_id):
    """
    Extract a document and replace its searchable chunks.

    This function does not call an AI provider or generate embeddings.
    """
    document = ProductKnowledgeDocument.objects.get(
        pk=document_id
    )

    if document.deleted_at or not document.is_active:
        raise ValidationError(
            "Inactive or deleted documents cannot be processed."
        )

    document.status = ProductKnowledgeDocument.Status.PROCESSING
    document.processing_attempts += 1
    document.processing_started_at = timezone.now()
    document.processing_completed_at = None
    document.processing_error = ""

    document.save(update_fields=[
        "status",
        "processing_attempts",
        "processing_started_at",
        "processing_completed_at",
        "processing_error",
        "updated_at",
    ])

    try:
        # Extract before touching existing chunks.
        result = _extract_from_storage(document)
        extracted_text = result["text"]
        passages = split_text_into_chunks(extracted_text)

        if not passages:
            raise DocumentExtractionError(
                "No searchable text was extracted from this document."
            )

        new_chunks = []

        for index, passage in enumerate(passages):
            content_hash = hashlib.sha256(
                passage.encode("utf-8")
            ).hexdigest()

            new_chunks.append(
                ProductKnowledgeChunk(
                    document_id=document_id,
                    organization_id=document.organization_id,
                    chunk_index=index,
                    text=passage,
                    token_count=max(1, len(passage) // 4),
                    content_hash=content_hash,
                    metadata={
                        "extraction_version": 1,
                        "chunking_method": "character_overlap",
                    },
                )
            )

        # Replace chunks and update document metadata atomically.
        # If this transaction fails, previous chunks are preserved.
        with transaction.atomic():
            locked_document = (
                ProductKnowledgeDocument.objects
                .select_for_update()
                .get(pk=document_id)
            )

            if locked_document.deleted_at or not locked_document.is_active:
                raise ValidationError(
                    "The document became inactive during processing."
                )

            ProductKnowledgeChunk.objects.filter(
                document=locked_document
            ).delete()

            ProductKnowledgeChunk.objects.bulk_create(new_chunks)

            locked_document.extracted_text = extracted_text
            locked_document.page_count = result["page_count"]
            locked_document.chunk_count = len(new_chunks)
            locked_document.file_extension = result["file_extension"]
            locked_document.status = (
                ProductKnowledgeDocument.Status.READY
            )
            locked_document.index_status = (
                ProductKnowledgeDocument.IndexStatus.PENDING
            )
            locked_document.processing_completed_at = timezone.now()
            locked_document.processing_error = ""

            locked_document.save(update_fields=[
                "extracted_text",
                "page_count",
                "chunk_count",
                "file_extension",
                "status",
                "index_status",
                "processing_completed_at",
                "processing_error",
                "updated_at",
            ])

        return locked_document

    except Exception as exc:
        logger.exception(
            "Knowledge document processing failed for document ID %s",
            document_id,
        )

        ProductKnowledgeDocument.objects.filter(
            pk=document_id
        ).update(
            status=ProductKnowledgeDocument.Status.FAILED,
            processing_error=str(exc)[:4000],
            processing_completed_at=timezone.now(),
            updated_at=timezone.now(),
        )

        raise
