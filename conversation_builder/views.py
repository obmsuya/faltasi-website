from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from organizations.models import OrganizationMember
from organizations.utils import (
    get_user_organization,
    is_platform_administrator,
)

from .models import ConversationConfiguration
from .services import (
    create_configuration,
    create_draft_version,
    publish_draft,
)

from products.models import Product

from .models import (
    ConversationConfiguration,
    ProductConversationConfiguration,
     ProductConversationVersion,
)

from .services import (
    create_configuration,
    create_draft_version,
    publish_draft,
    create_product_configuration,
    create_product_draft_version,
    publish_product_draft,
)



def get_builder_access(request, publish=False):
    """
    Resolve the active organization and enforce Conversation Builder access.
    Platform administrators retain their platform-level privileges.
    """
    organization = get_user_organization(request.user, request)

    if not organization:
        raise PermissionDenied(
            "No active organization is available."
        )

    platform_admin = is_platform_administrator(request.user)

    membership = OrganizationMember.objects.filter(
        user=request.user,
        organization=organization,
        is_active=True,
        organization__status="active",
    ).first()

    if not platform_admin and not membership:
        raise PermissionDenied(
            "You do not have access to this organization's configuration."
        )

    role = membership.role if membership else None

    can_edit = platform_admin or role in ["owner", "admin", "manager"]
    can_publish = platform_admin or role in ["owner", "admin"]

    if publish and not can_publish:
        raise PermissionDenied(
            "Only organization owners and administrators can publish configurations."
        )

    if not publish and not can_edit:
        raise PermissionDenied(
            "You do not have permission to access the Conversation Builder."
        )

    return organization, can_edit, can_publish


@login_required
def overview(request):
    organization, can_edit, can_publish = get_builder_access(request)

    configuration = (
        ConversationConfiguration.objects
        .filter(organization=organization)
        .select_related("draft_version", "published_version")
        .first()
    )

    versions = (
        configuration.versions.all()
        if configuration
        else []
    )

    return render(
        request,
        "conversation_builder/overview.html",
        {
            "organization": organization,
            "configuration": configuration,
            "versions": versions,
            "can_edit": can_edit,
            "can_publish": can_publish,
        },
    )


@login_required
@require_POST
def create_configuration_view(request):
    organization, can_edit, can_publish = get_builder_access(request)

    existing = ConversationConfiguration.objects.filter(
        organization=organization
    ).first()

    if existing:
        messages.info(
            request,
            "A conversation configuration already exists."
        )
        return redirect("conversation_builder:overview")

    try:
        create_configuration(
            organization=organization,
            actor=request.user,
        )
        messages.success(
            request,
            "Conversation configuration created successfully."
        )
    except ValidationError as exc:
        messages.error(request, str(exc))

    return redirect("conversation_builder:overview")


@login_required
@require_POST
def create_draft_view(request):
    organization, can_edit, can_publish = get_builder_access(request)

    configuration = get_object_or_404(
        ConversationConfiguration,
        organization=organization,
    )

    try:
        create_draft_version(
            configuration_id=configuration.id,
            organization_id=organization.id,
            actor=request.user,
        )
        messages.success(
            request,
            "A new draft version has been created."
        )
    except ValidationError as exc:
        messages.error(request, str(exc))

    return redirect("conversation_builder:overview")


@login_required
@require_POST
def publish_draft_view(request):
    organization, can_edit, can_publish = get_builder_access(
        request,
        publish=True,
    )

    configuration = get_object_or_404(
        ConversationConfiguration,
        organization=organization,
    )

    try:
        publish_draft(
            configuration_id=configuration.id,
            organization_id=organization.id,
            actor=request.user,
        )
        messages.success(
            request,
            "Conversation configuration published successfully."
        )
    except ValidationError as exc:
        messages.error(request, str(exc))

    return redirect("conversation_builder:overview")


@login_required
def product_conversations(request):
    organization, can_edit, can_publish = get_builder_access(request)

    products = Product.objects.filter(
        organization=organization,
        organization__status="active",
        show_on_whatsapp=True,
        is_active=True,
        deleted_at__isnull=True,
    ).order_by("name")

    configurations = (
        ProductConversationConfiguration.objects
        .filter(organization=organization)
        .select_related(
            "product",
            "draft_version",
            "published_version",
        )
    )

    configurations_by_product = {
        configuration.product_id: configuration
        for configuration in configurations
    }

    product_rows = [
        {
            "product": product,
            "configuration": configurations_by_product.get(product.pk),
        }
        for product in products
    ]

    return render(
        request,
        "conversation_builder/product_conversations.html",
        {
            "organization": organization,
            "product_rows": product_rows,
            "can_edit": can_edit,
            "can_publish": can_publish,
        },
    )


@login_required
@require_POST
def create_product_configuration_view(request):
    organization, can_edit, can_publish = get_builder_access(request)

    product_id = request.POST.get("product_id")

    if not product_id:
        messages.error(request, "Please select a product.")
        return redirect("conversation_builder:product_conversations")

    try:
        create_product_configuration(
            product_id=product_id,
            organization_id=organization.pk,
            actor=request.user,
        )

        messages.success(
            request,
            "Product conversation configuration created successfully.",
        )

    except ValidationError as exc:
        messages.error(request, "; ".join(exc.messages))

    return redirect("conversation_builder:product_conversations")

@login_required
def edit_product_configuration_view(request, configuration_id):
    organization, can_edit, can_publish = get_builder_access(request)

    configuration = get_object_or_404(
        ProductConversationConfiguration.objects.select_related(
            "product",
            "draft_version",
        ),
        pk=configuration_id,
        organization=organization,
    )

    draft = configuration.draft_version

    if not draft or draft.configuration_id != configuration.pk:
        messages.error(
            request,
            "No editable draft exists for this product. Create a new draft first.",
        )
        return redirect("conversation_builder:product_conversations")

    if draft.status != "draft":
        raise PermissionDenied(
            "Only draft product conversations can be edited."
        )

    if request.method == "POST":
        allowed_languages = dict(
            ProductConversationVersion.LANGUAGE_CHOICES
        )

        language = request.POST.get("default_language", "auto")
        if language not in allowed_languages:
            messages.error(request, "Please select a valid language.")
            return redirect(
                "conversation_builder:edit_product_configuration",
                configuration_id=configuration.pk,
            )

        draft.default_language = language
        draft.welcome_message = request.POST.get("welcome_message", "").strip()
        draft.fallback_message = request.POST.get("fallback_message", "").strip()
        draft.closing_message = request.POST.get("closing_message", "").strip()
        draft.handover_message = request.POST.get("handover_message", "").strip()
        draft.ai_instructions = request.POST.get("ai_instructions", "").strip()

        draft.save(update_fields=[
            "default_language",
            "welcome_message",
            "fallback_message",
            "closing_message",
            "handover_message",
            "ai_instructions",
            "updated_at",
        ])

        messages.success(request, "Product conversation draft saved successfully.")

        return redirect(
            "conversation_builder:edit_product_configuration",
            configuration_id=configuration.pk,
        )

    return render(
        request,
        "conversation_builder/product_conversation_editor.html",
        {
            "organization": organization,
            "configuration": configuration,
            "product": configuration.product,
            "draft": draft,
            "can_edit": can_edit,
            "can_publish": can_publish,
        },
    )



@login_required
@require_POST
def publish_product_draft_view(request, configuration_id):
    organization, can_edit, can_publish = get_builder_access(
        request,
        publish=True,
    )

    configuration = get_object_or_404(
        ProductConversationConfiguration,
        pk=configuration_id,
        organization=organization,
    )

    try:
        publish_product_draft(
            configuration_id=configuration.pk,
            organization_id=organization.pk,
            actor=request.user,
        )

        messages.success(
            request,
            "Product conversation configuration published successfully.",
        )

    except ValidationError as exc:
        messages.error(request, "; ".join(exc.messages))

        return redirect(
            "conversation_builder:edit_product_configuration",
            configuration_id=configuration.pk,
        )

    return redirect("conversation_builder:product_conversations")

@login_required
@require_POST
def create_product_draft_view(request, configuration_id):
    organization, can_edit, can_publish = get_builder_access(request)

    configuration = get_object_or_404(
        ProductConversationConfiguration,
        pk=configuration_id,
        organization=organization,
    )

    try:
        draft = create_product_draft_version(
            configuration_id=configuration.pk,
            organization_id=organization.pk,
            actor=request.user,
        )

        messages.success(
            request,
            f"Product conversation draft Version {draft.version_number} "
            "created successfully.",
        )

        return redirect(
            "conversation_builder:edit_product_configuration",
            configuration_id=configuration.pk,
        )

    except ValidationError as exc:
        messages.error(request, "; ".join(exc.messages))

    return redirect("conversation_builder:product_conversations")
