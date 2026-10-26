
import logging
import os

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.http import HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from organizations.models import Organization, OrganizationMember

from .extractors import DocumentExtractionError
from .models import (
    ALLOWED_DOCUMENT_EXTENSIONS,
    MAX_DOCUMENT_SIZE,
    ProductKnowledgeDocument,
)
from .processing import process_document

logger = logging.getLogger(__name__)

# Keep these permission rules centralized so they can be changed deliberately.
DOCUMENT_MANAGER_ROLES = {"owner", "admin"}


def _get_document_access(request):
    """
    Return the organization and access permissions for the current user.

    Normal users must have an active membership in an active organization.
    Superusers use the existing active_organization_id session selection,
    with the existing platform-owner fallback.
    """
    user = request.user

    if user.is_superuser:
        organization = None
        selected_id = request.session.get("active_organization_id")

        if selected_id:
            organization = Organization.objects.filter(
                pk=selected_id,
                status="active",
            ).first()

            if organization is None:
                request.session.pop("active_organization_id", None)

        if organization is None:
            organization = Organization.objects.filter(
                organization_type="platform_owner",
                status="active",
            ).order_by("id").first()

        # A superuser can manage documents for the selected organization.
        return organization, True

    membership = (
        OrganizationMember.objects
        .select_related("organization")
        .filter(
            user=user,
            is_active=True,
            organization__status="active",
        )
        .order_by("id")
        .first()
    )

    if membership is None:
        return None, False

    can_manage = membership.role in DOCUMENT_MANAGER_ROLES
    return membership.organization, can_manage


@login_required
def document_list(request):
    organization, can_manage = _get_document_access(request)

    if organization is None:
        return HttpResponseForbidden(
            "You do not have access to an active organization."
        )

    documents = ProductKnowledgeDocument.objects.filter(
        organization=organization,
        deleted_at__isnull=True,
    ).order_by("-uploaded_at")

    return render(
        request,
        "product_knowledge/document_list.html",
        {
            "organization": organization,
            "documents": documents,
            "can_manage": can_manage,
            "allowed_extensions": ALLOWED_DOCUMENT_EXTENSIONS,
            "max_document_size_mb": MAX_DOCUMENT_SIZE // (1024 * 1024),
            "document_type_choices": ProductKnowledgeDocument.DocumentType.choices,
        },
    )


@login_required
@require_POST
def document_upload(request):
    organization, can_manage = _get_document_access(request)

    if organization is None:
        return HttpResponseForbidden(
            "You do not have access to an active organization."
        )

    if not can_manage:
        return HttpResponseForbidden(
            "Only organization owners and administrators can upload documents."
        )

    uploaded_file = request.FILES.get("file")
    title = request.POST.get("title", "").strip()
    description = request.POST.get("description", "").strip()
    document_type = request.POST.get("document_type", "").strip()

    if not uploaded_file:
        messages.error(request, "Choose a document to upload.")
        return redirect("product_knowledge:document_list")

    if not title or len(title) > 255:
        messages.error(
            request,
            "Enter a document title of no more than 255 characters.",
        )
        return redirect("product_knowledge:document_list")

    if len(description) > 10000:
        messages.error(request, "The description is too long.")
        return redirect("product_knowledge:document_list")

    valid_document_types = {
        choice[0] for choice in ProductKnowledgeDocument.DocumentType.choices
    }
    if document_type not in valid_document_types:
        messages.error(request, "Choose a valid document type.")
        return redirect("product_knowledge:document_list")

    extension = os.path.splitext(uploaded_file.name)[1].lower().lstrip(".")
    if extension not in ALLOWED_DOCUMENT_EXTENSIONS:
        messages.error(
            request,
            "Unsupported file type. Allowed types: "
            + ", ".join(ALLOWED_DOCUMENT_EXTENSIONS),
        )
        return redirect("product_knowledge:document_list")

    if uploaded_file.size <= 0 or uploaded_file.size > MAX_DOCUMENT_SIZE:
        messages.error(
            request,
            f"The file must be between 1 byte and "
            f"{MAX_DOCUMENT_SIZE // (1024 * 1024)} MB.",
        )
        return redirect("product_knowledge:document_list")

    document = ProductKnowledgeDocument(
        organization=organization,
        uploaded_by=request.user,
        title=title,
        description=description,
        document_type=document_type,
        original_filename=os.path.basename(uploaded_file.name)[:255],
        status=ProductKnowledgeDocument.Status.PENDING,
        index_status=ProductKnowledgeDocument.IndexStatus.NOT_INDEXED,
        file=uploaded_file,
    )

    try:
        # Model validation checks the extension, size, basic content and
        # product/organization ownership before the file is saved.
        document.full_clean()
        document.save()
    except ValidationError as exc:
        logger.info(
            "Document upload validation rejected for organization %s",
            organization.pk,
        )
        messages.error(
            request,
            "The document could not be accepted. Check its title and file type.",
        )
        return redirect("product_knowledge:document_list")
    except Exception:
        logger.exception(
            "Document upload failed for organization %s",
            organization.pk,
        )
        messages.error(
            request,
            "The document could not be saved. Please try again.",
        )
        return redirect("product_knowledge:document_list")

    messages.success(
        request,
        "Document uploaded successfully. You can now process it.",
    )
    return redirect("product_knowledge:document_list")


@login_required
@require_POST
def document_process(request, document_id):
    organization, can_manage = _get_document_access(request)

    if organization is None:
        return HttpResponseForbidden(
            "You do not have access to an active organization."
        )

    if not can_manage:
        return HttpResponseForbidden(
            "Only organization owners and administrators can process documents."
        )

    document = get_object_or_404(
        ProductKnowledgeDocument,
        pk=document_id,
        organization=organization,
        deleted_at__isnull=True,
        is_active=True,
    )

    if document.status == ProductKnowledgeDocument.Status.ARCHIVED:
        messages.error(request, "Archived documents cannot be processed.")
        return redirect("product_knowledge:document_list")

    try:
        process_document(document.pk)
    except (DocumentExtractionError, OSError, ValueError):
        logger.warning(
            "Document processing could not complete for document %s "
            "in organization %s",
            document.pk,
            organization.pk,
            exc_info=True,
        )
        messages.error(
            request,
            "The document could not be processed. Check that it is valid "
            "and contains readable text.",
        )
    except Exception:
        logger.exception(
            "Unexpected document processing error for document %s "
            "in organization %s",
            document.pk,
            organization.pk,
        )
        messages.error(
            request,
            "Document processing failed. Please try again or contact support.",
        )
    else:
        messages.success(
            request,
            "Document processing completed successfully.",
        )

    return redirect("product_knowledge:document_list")
