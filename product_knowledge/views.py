
import logging
import os

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.http import HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from organizations.models import Organization, OrganizationMember

from .ai_service import (
    AIStaffConfigurationError,
    AIStaffError,
    AIStaffUnavailableError,
    generate_answer,
)
from .extractors import DocumentExtractionError
from .models import (
    ALLOWED_DOCUMENT_EXTENSIONS,
    MAX_DOCUMENT_SIZE,
    ProductKnowledgeDocument,
)
from .processing import process_document
from organizations.utils import get_user_organization


logger = logging.getLogger(__name__)

# Only owners and administrators can manage knowledge documents.
# This does NOT restrict AI Assistant access.
DOCUMENT_MANAGER_ROLES = {"owner", "admin"}



def _get_document_access(request):
    """
    Return the organization and document-management permissions.

    Organization selection uses the shared platform resolver.
    Document management remains restricted to owners and administrators.
    AI Assistant access remains separate.
    """
    organization = get_user_organization(
        request.user,
        request=request,
    )

    if organization is None:
        return None, False

    if request.user.is_superuser:
        return organization, True

    membership = (
        OrganizationMember.objects
        .filter(
            user=request.user,
            organization=organization,
            is_active=True,
            organization__status="active",
        )
        .first()
    )

    if membership is None:
        return None, False

    can_manage = membership.role in DOCUMENT_MANAGER_ROLES

    return organization, can_manage

def _can_access_admin_documents(request, organization):
    """Use the verified membership for this exact organization."""
    if request.user.is_superuser:
        return True

    return OrganizationMember.objects.filter(
        user=request.user,
        organization=organization,
        is_active=True,
        organization__status="active",
        role__in=DOCUMENT_MANAGER_ROLES,
    ).exists()


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
            "document_type_choices": (
                ProductKnowledgeDocument.DocumentType.choices
            ),
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
    access_level = request.POST.get(
        "access_level",
        ProductKnowledgeDocument.AccessLevel.ADMIN_ONLY,
    ).strip()

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
        choice[0]
        for choice in ProductKnowledgeDocument.DocumentType.choices
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

    valid_access_levels = {
        choice[0] for choice in ProductKnowledgeDocument.AccessLevel.choices
    }
    if access_level not in valid_access_levels:
        access_level = ProductKnowledgeDocument.AccessLevel.ADMIN_ONLY

    document = ProductKnowledgeDocument(
        organization=organization,
        access_level=access_level,
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
        # Model validation checks the extension, size, basic content
        # and product/organization ownership before the file is saved.
        document.full_clean()
        document.save()

    except ValidationError:
        logger.info(
            "Document upload validation rejected for organization %s",
            organization.pk,
        )
        messages.error(
            request,
            "The document could not be accepted. "
            "Check its title and file type.",
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
def document_update_access(request, document_id):
    """Allow owners/admins to change AI STAFF visibility for one document."""
    organization, can_manage = _get_document_access(request)

    if organization is None:
        return HttpResponseForbidden(
            "You do not have access to an active organization."
        )
    if not can_manage:
        return HttpResponseForbidden(
            "Only organization owners and administrators can change document access."
        )

    document = get_object_or_404(
        ProductKnowledgeDocument,
        pk=document_id,
        organization=organization,
        deleted_at__isnull=True,
    )
    access_level = request.POST.get("access_level", "").strip()
    valid_access_levels = {
        choice[0] for choice in ProductKnowledgeDocument.AccessLevel.choices
    }
    if access_level not in valid_access_levels:
        messages.error(request, "Choose a valid document access level.")
        return redirect("product_knowledge:document_list")

    document.access_level = access_level
    document.save(update_fields=["access_level", "updated_at"])
    messages.success(request, "Document access level updated.")
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
            "The document could not be processed. "
            "Check that it is valid and contains readable text.",
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


def _get_ai_organization(request):
    """
    Resolve the organization for the AI Assistant.

    All active organization employees are allowed to use AI.

    Normal users:
        - Must have an active organization membership.
        - If they belong to one organization, it is selected automatically.
        - If they belong to multiple organizations, they must select one.
        - Their membership is verified on every request.

    Superusers:
        - Use the existing active_organization_id session selection.
        - Fall back to the first active platform-owner organization.
    """
    user = request.user

    if user.is_superuser:
        selected_id = request.session.get("active_organization_id")

        if selected_id:
            organization = Organization.objects.filter(
                pk=selected_id,
                status="active",
            ).first()

            if organization:
                return organization, None

            request.session.pop("active_organization_id", None)

        organization = Organization.objects.filter(
            organization_type="platform_owner",
            status="active",
        ).order_by("id").first()

        if organization is None:
            return None, "No active organization is available."

        return organization, None

    memberships = (
        OrganizationMember.objects
        .select_related("organization")
        .filter(
            user=user,
            is_active=True,
            organization__status="active",
        )
        .order_by("organization__name", "id")
    )

    selected_id = request.session.get("ai_active_organization_id")

    if selected_id:
        membership = memberships.filter(
            organization_id=selected_id,
        ).first()

        if membership:
            return membership.organization, None

        # Remove stale or unauthorized organization selections.
        request.session.pop("ai_active_organization_id", None)

    membership_count = memberships.count()

    if membership_count == 0:
        return (
            None,
            "Your account has no active organization membership.",
        )

    if membership_count > 1:
        return (
            None,
            "Please select an organization before using AI.",
        )

    membership = memberships.first()

    return membership.organization, None


@login_required
def ai_assistant(request):
    """
    Organization-scoped AI question and answer page.

    All active employees of the selected organization can use AI.
    AI requests do not modify business records.
    """

    # ---------------------------------------------------------
    # ORGANIZATION SELECTION
    # ---------------------------------------------------------

    if (
        request.method == "POST"
        and request.POST.get("action") == "select_organization"
    ):
        if request.user.is_superuser:
            return HttpResponseForbidden(
                "Platform administrators must use "
                "the platform organization switcher."
            )

        organization_id = request.POST.get(
            "organization_id",
            "",
        ).strip()

        # Validate the submitted ID before querying the database.
        try:
            organization_id = int(organization_id)

        except (TypeError, ValueError):
            return HttpResponseForbidden(
                "Please select a valid organization."
            )

        # Verify that this user is an active member of the organization.
        membership = (
            OrganizationMember.objects
            .select_related("organization")
            .filter(
                user=request.user,
                organization_id=organization_id,
                is_active=True,
                organization__status="active",
            )
            .first()
        )

        if membership is None:
            return HttpResponseForbidden(
                "You are not authorized to select that organization."
            )

        request.session["ai_active_organization_id"] = (
            membership.organization_id
        )

        return redirect("product_knowledge:ai_assistant")

    # ---------------------------------------------------------
    # RESOLVE ACTIVE ORGANIZATION
    # ---------------------------------------------------------

    organization, access_error = _get_ai_organization(request)

    if access_error:
        if request.method == "POST":
            return HttpResponseForbidden(access_error)

        memberships = []

        if not request.user.is_superuser:
            memberships = list(
                OrganizationMember.objects
                .select_related("organization")
                .filter(
                    user=request.user,
                    is_active=True,
                    organization__status="active",
                )
                .order_by("organization__name")
            )

        return render(
            request,
            "product_knowledge/ai_assistant.html",
            {
                "organization": None,
                "access_error": access_error,
                "memberships": memberships,
                "answer": None,
                "sources": None,
                "question": "",
                "can_ask": False,
            },
        )

    # ---------------------------------------------------------
    # PROCESS AI QUESTION
    # ---------------------------------------------------------

    if request.method == "POST":
        question = request.POST.get("question", "").strip()

        if not question:
            return render(
                request,
                "product_knowledge/ai_assistant.html",
                {
                    "organization": organization,
                    "answer": None,
                    "sources": None,
                    "question": question,
                    "error": "Enter a question before submitting.",
                    "can_ask": True,
                },
            )

        # Initialize both variables before calling the AI service.
        error = None
        result = None

        can_access_admin_only = _can_access_admin_documents(
            request, organization
        )

        try:
            result = generate_answer(
                organization,
                question,
                can_access_admin_only=can_access_admin_only,
            )

        except ValueError as exc:
            return render(
                request,
                "product_knowledge/ai_assistant.html",
                {
                    "organization": organization,
                    "answer": None,
                    "sources": None,
                    "question": question,
                    "error": str(exc),
                    "can_ask": True,
                },
            )

        except AIStaffConfigurationError:
            logger.error(
                "AI configuration error for organization %s",
                organization.pk,
                exc_info=True,
            )

            error = (
                "AI is not configured correctly. "
                "Please contact support."
            )

        except AIStaffUnavailableError:
            logger.warning(
                "AI provider unavailable for organization %s",
                organization.pk,
                exc_info=True,
            )

            error = (
                "AI is temporarily unavailable. "
                "Please try again later."
            )

        except AIStaffError:
            logger.exception(
                "AI service error for organization %s",
                organization.pk,
            )

            error = (
                "AI could not retrieve the organization's knowledge."
            )

        except Exception:
            logger.exception(
                "Unexpected AI error for organization %s",
                organization.pk,
            )

            error = "An unexpected error occurred. Please try again."

        # -----------------------------------------------------
        # DISPLAY AI RESPONSE
        # -----------------------------------------------------

        return render(
            request,
            "product_knowledge/ai_assistant.html",
            {
                "organization": organization,
                "answer": result["answer"] if result else None,
                "sources": result["sources"] if result else None,
                "model": result["model"] if result else None,
                "question": question,
                "error": error,
                "can_ask": True,
            },
        )

    # ---------------------------------------------------------
    # DISPLAY AI PAGE
    # ---------------------------------------------------------

    return render(
        request,
        "product_knowledge/ai_assistant.html",
        {
            "organization": organization,
            "answer": None,
            "sources": None,
            "question": "",
            "can_ask": True,
        },
    )
