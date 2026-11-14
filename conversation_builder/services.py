
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from .models import (
    ConversationConfiguration,
    ConversationConfigurationVersion,
    ConversationQuestion,
    ConversationOption,
    ConversationCategoryRule,
    ConversationConfigurationAudit,
)
from .validators import validate_version_for_publish

from products.models import Product
from whatsapp.ai_service import _product_context

from .models import (
    ProductConversationConfiguration,
    ProductConversationVersion,
    ProductConversationQuestion,
    ProductConversationOption,
    ProductConversationConfigurationAudit,
)

from .validators import (
    validate_question,
    validate_question_dependencies,
)


def record_configuration_audit(
    configuration,
    action,
    actor=None,
    version=None,
    details=None,
):
    audit = ConversationConfigurationAudit(
        configuration=configuration,
        version=version,
        actor=actor,
        action=action,
        details=details or {},
    )
    audit.full_clean()
    audit.save()
    return audit


def build_version_snapshot(version):
    """Build a complete JSON snapshot of the configuration."""

    questions = []

    for question in version.questions.prefetch_related("options").all():
        questions.append({
            "key": question.key,
            "scope": question.scope,
            "question": question.question,
            "field_type": question.field_type,
            "help_text": question.help_text,
            "retry_message": question.retry_message,
            "skip_message": question.skip_message,
            "is_required": question.is_required,
            "allow_skip": question.allow_skip,
            "is_active": question.is_active,
            "order": question.order,
            "max_attempts": question.max_attempts,
            "validation_rules": question.validation_rules,
            "translations": question.translations,
            "display_conditions": question.display_conditions,
            "options": [
                {
                    "value": option.value,
                    "label": option.label,
                    "translations": option.translations,
                    "order": option.order,
                    "is_active": option.is_active,
                }
                for option in question.options.all()
            ],
        })

    category_rules = [
        {
            "category_id": rule.category_id,
            "category_name": rule.category.name,
            "is_enabled": rule.is_enabled,
            "priority": rule.priority,
            "instructions": rule.instructions,
            "welcome_message": rule.welcome_message,
            "closing_message": rule.closing_message,
        }
        for rule in version.category_rules.select_related("category").all()
    ]

    return {
        "version_number": version.version_number,
        "default_language": version.default_language,
        "welcome_message": version.welcome_message,
        "fallback_message": version.fallback_message,
        "closing_message": version.closing_message,
        "handover_message": version.handover_message,
        "ai_instructions": version.ai_instructions,
        "settings": version.settings,
        "questions": questions,
        "category_rules": category_rules,
    }


@transaction.atomic
def create_configuration(organization, actor=None):
    """Create an organization's configuration and its first draft."""

    configuration = ConversationConfiguration(
        organization=organization,
    )
    configuration.full_clean()
    configuration.save()

    version = ConversationConfigurationVersion(
        configuration=configuration,
        version_number=1,
        status="draft",
        created_by=actor,
    )
    version.full_clean()
    version.save()

    configuration.draft_version = version
    configuration.full_clean()
    configuration.save(update_fields=["draft_version", "updated_at"])

    record_configuration_audit(
        configuration=configuration,
        version=version,
        actor=actor,
        action="created",
        details={"version_number": 1},
    )

    return configuration, version


@transaction.atomic
def create_draft_version(configuration_id, organization_id, actor=None):
    """
    Create a new editable draft based on the published version.

    Only one draft per organization configuration is allowed.
    """

    configuration = (
        ConversationConfiguration.objects
        .select_for_update()
        .get(
            pk=configuration_id,
            organization_id=organization_id,
        )
    )

    if configuration.draft_version_id:
        raise ValidationError(
            "A draft already exists. Edit the existing draft instead."
        )

    published = None

    if configuration.published_version_id:
        published = (
            ConversationConfigurationVersion.objects
            .select_for_update()
            .get(
                pk=configuration.published_version_id,
                configuration=configuration,
                status="published",
            )
        )

    latest_number = (
        configuration.versions.order_by("-version_number")
        .values_list("version_number", flat=True)
        .first()
        or 0
    )

    version = ConversationConfigurationVersion(
        configuration=configuration,
        version_number=latest_number + 1,
        status="draft",
        created_by=actor,
    )

    if published:
        version.default_language = published.default_language
        version.welcome_message = published.welcome_message
        version.fallback_message = published.fallback_message
        version.closing_message = published.closing_message
        version.handover_message = published.handover_message
        version.ai_instructions = published.ai_instructions
        version.settings = published.settings.copy()
        version.snapshot = {}

    version.full_clean()
    version.save()

    if published:
        for old_question in published.questions.all():
            new_question = ConversationQuestion(
                version=version,
                key=old_question.key,
                scope=old_question.scope,
                question=old_question.question,
                field_type=old_question.field_type,
                help_text=old_question.help_text,
                retry_message=old_question.retry_message,
                skip_message=old_question.skip_message,
                is_required=old_question.is_required,
                allow_skip=old_question.allow_skip,
                is_active=old_question.is_active,
                order=old_question.order,
                max_attempts=old_question.max_attempts,
                validation_rules=old_question.validation_rules.copy(),
                translations=old_question.translations.copy(),
                display_conditions=old_question.display_conditions.copy(),
            )
            new_question.full_clean()
            new_question.save()

            for old_option in old_question.options.all():
                new_option = ConversationOption(
                    question=new_question,
                    value=old_option.value,
                    label=old_option.label,
                    translations=old_option.translations.copy(),
                    order=old_option.order,
                    is_active=old_option.is_active,
                )
                new_option.full_clean()
                new_option.save()

        for old_rule in published.category_rules.all():
            new_rule = ConversationCategoryRule(
                version=version,
                category=old_rule.category,
                is_enabled=old_rule.is_enabled,
                priority=old_rule.priority,
                instructions=old_rule.instructions,
                welcome_message=old_rule.welcome_message,
                closing_message=old_rule.closing_message,
            )
            new_rule.full_clean()
            new_rule.save()

    configuration.draft_version = version
    configuration.full_clean()
    configuration.save(update_fields=["draft_version", "updated_at"])

    record_configuration_audit(
        configuration=configuration,
        version=version,
        actor=actor,
        action="draft_created",
        details={
            "version_number": version.version_number,
            "copied_from": published.version_number if published else None,
        },
    )

    return version


@transaction.atomic
def publish_draft(configuration_id, organization_id, actor=None):
    """
    Validate and atomically publish the current draft.

    Existing published content is never edited. Only its status
    changes to archived when a replacement is published.
    """

    configuration = (
        ConversationConfiguration.objects
        .select_for_update()
        .get(
            pk=configuration_id,
            organization_id=organization_id,
        )
    )

    if not configuration.draft_version_id:
        raise ValidationError("There is no draft available to publish.")

    draft = (
        ConversationConfigurationVersion.objects
        .select_for_update()
        .get(
            pk=configuration.draft_version_id,
            configuration=configuration,
            status="draft",
        )
    )

    # Validate the complete draft before changing publication state.
    validate_version_for_publish(draft)

    snapshot = build_version_snapshot(draft)
    now = timezone.now()

    previous = configuration.published_version_id

    if previous:
        previous_version = (
            ConversationConfigurationVersion.objects
            .select_for_update()
            .get(
                pk=previous,
                configuration=configuration,
                status="published",
            )
        )

        # Controlled status transition. Do not edit its content.
        ConversationConfigurationVersion.objects.filter(
            pk=previous_version.pk,
            status="published",
        ).update(status="archived")

    # Controlled publication transition. The model save guard
    # intentionally prevents ordinary edits to published versions.
    ConversationConfigurationVersion.objects.filter(
        pk=draft.pk,
        status="draft",
    ).update(
        status="published",
        snapshot=snapshot,
        published_by=actor,
        published_at=now,
        updated_at=now,
    )

    configuration.published_version_id = draft.pk
    configuration.draft_version = None
    configuration.full_clean()
    configuration.save(
        update_fields=[
            "published_version",
            "draft_version",
            "updated_at",
        ]
    )

    record_configuration_audit(
        configuration=configuration,
        version=draft,
        actor=actor,
        action="published",
        details={
            "version_number": draft.version_number,
            "previous_version_id": previous,
            "published_at": now.isoformat(),
        },
    )

    return ConversationConfigurationVersion.objects.get(pk=draft.pk)

# ==========================================================
# PRODUCT CONVERSATION SERVICES
# ==========================================================

def get_eligible_whatsapp_product(product_id, organization_id):
    """
    Retrieve a WhatsApp-enabled product within its owning organization.
    Never substitute products from another organization.
    """

    product = Product.objects.filter(
        pk=product_id,
        organization_id=organization_id,
        organization__status="active",
        show_on_whatsapp=True,
        is_active=True,
        deleted_at__isnull=True,
    ).select_related("organization").first()

    if not product:
        raise ValidationError(
            "Product is unavailable for WhatsApp conversations."
        )

    if not product.organization_id:
        raise ValidationError(
            "Product must belong to an organization."
        )

    return product


def build_product_snapshot(product):
    """
    Reuse the existing WhatsApp customer-facing product context.
    Internal prices and inventory quantities are excluded.
    """

    return _product_context(product)


def record_product_configuration_audit(
    configuration,
    action,
    actor=None,
    version=None,
    details=None,
):
    audit = ProductConversationConfigurationAudit(
        configuration=configuration,
        version=version,
        actor=actor,
        action=action,
        details=details or {},
    )

    audit.full_clean()
    audit.save()

    return audit


@transaction.atomic
def create_product_configuration(
    product_id,
    organization_id,
    actor=None,
):
    """
    Create one product conversation configuration
    and its first draft version.
    """

    product = get_eligible_whatsapp_product(
        product_id,
        organization_id,
    )

    if ProductConversationConfiguration.objects.filter(
        product=product
    ).exists():
        raise ValidationError(
            "A conversation configuration already exists for this product."
        )

    configuration = ProductConversationConfiguration(
        organization=product.organization,
        product=product,
        is_enabled=True,
    )

    configuration.full_clean()
    configuration.save()

    version = ProductConversationVersion(
        configuration=configuration,
        version_number=1,
        status="draft",
        created_by=actor,
        product_snapshot=build_product_snapshot(product),
    )

    version.full_clean()
    version.save()

    configuration.draft_version = version
    configuration.full_clean()
    configuration.save(
        update_fields=["draft_version", "updated_at"]
    )

    record_product_configuration_audit(
        configuration=configuration,
        version=version,
        actor=actor,
        action="created",
        details={"version_number": 1},
    )

    return configuration, version


def build_product_version_snapshot(version):
    """
    Build the immutable published representation of a product conversation.
    """

    questions = []

    for question in version.questions.prefetch_related(
        "options"
    ).all():

        questions.append({
            "key": question.key,
            "question": question.question,
            "help_text": question.help_text,
            "field_type": question.field_type,
            "is_required": question.is_required,
            "allow_skip": question.allow_skip,
            "is_active": question.is_active,
            "order": question.order,
            "max_attempts": question.max_attempts,
            "retry_message": question.retry_message,
            "skip_message": question.skip_message,
            "validation_rules": question.validation_rules,
            "translations": question.translations,
            "display_conditions": question.display_conditions,
            "options": [
                {
                    "value": option.value,
                    "label": option.label,
                    "translations": option.translations,
                    "order": option.order,
                    "is_active": option.is_active,
                }
                for option in question.options.all()
            ],
        })

    return {
        "version_number": version.version_number,
        "default_language": version.default_language,
        "welcome_message": version.welcome_message,
        "fallback_message": version.fallback_message,
        "closing_message": version.closing_message,
        "handover_message": version.handover_message,
        "ai_instructions": version.ai_instructions,
        "product": version.product_snapshot,
        "questions": questions,
    }


@transaction.atomic
def create_product_draft_version(
    configuration_id,
    organization_id,
    actor=None,
):
    """
    Create a new product draft from the previous published version.
    An existing draft is never silently overwritten.
    """

    configuration = (
        ProductConversationConfiguration.objects
        .select_for_update()
        .get(
            pk=configuration_id,
            organization_id=organization_id,
        )
    )

    product = get_eligible_whatsapp_product(
        configuration.product_id,
        organization_id,
    )

    if configuration.draft_version_id:
        raise ValidationError(
            "A product conversation draft already exists. "
            "Edit the existing draft instead."
        )

    published = None

    if configuration.published_version_id:
        published = (
            ProductConversationVersion.objects
            .select_for_update()
            .get(
                pk=configuration.published_version_id,
                configuration=configuration,
                status="published",
            )
        )

    latest_number = (
        configuration.versions
        .order_by("-version_number")
        .values_list("version_number", flat=True)
        .first()
        or 0
    )

    version = ProductConversationVersion(
        configuration=configuration,
        version_number=latest_number + 1,
        status="draft",
        created_by=actor,
        product_snapshot=build_product_snapshot(product),
    )

    if published:
        version.default_language = published.default_language
        version.welcome_message = published.welcome_message
        version.fallback_message = published.fallback_message
        version.closing_message = published.closing_message
        version.handover_message = published.handover_message
        version.ai_instructions = published.ai_instructions
        version.generation_metadata = (
            published.generation_metadata.copy()
        )

    version.full_clean()
    version.save()

    if published:
        for old_question in published.questions.prefetch_related(
            "options"
        ).all():

            new_question = ProductConversationQuestion(
                version=version,
                key=old_question.key,
                question=old_question.question,
                help_text=old_question.help_text,
                field_type=old_question.field_type,
                is_required=old_question.is_required,
                allow_skip=old_question.allow_skip,
                is_active=old_question.is_active,
                order=old_question.order,
                max_attempts=old_question.max_attempts,
                retry_message=old_question.retry_message,
                skip_message=old_question.skip_message,
                validation_rules=old_question.validation_rules.copy(),
                translations=old_question.translations.copy(),
                display_conditions=old_question.display_conditions.copy(),
                generation_rationale=old_question.generation_rationale,
            )

            new_question.full_clean()
            new_question.save()

            for old_option in old_question.options.all():
                new_option = ProductConversationOption(
                    question=new_question,
                    value=old_option.value,
                    label=old_option.label,
                    translations=old_option.translations.copy(),
                    order=old_option.order,
                    is_active=old_option.is_active,
                )

                new_option.full_clean()
                new_option.save()

    configuration.draft_version = version
    configuration.full_clean()
    configuration.save(
        update_fields=["draft_version", "updated_at"]
    )

    record_product_configuration_audit(
        configuration=configuration,
        version=version,
        actor=actor,
        action="draft_created",
        details={
            "version_number": version.version_number,
            "copied_from": (
                published.version_number if published else None
            ),
        },
    )

    return version


def validate_product_version_for_publish(version):
    """
    Validate all active product questions and dependencies.
    """

    errors = {}

    if version.status != "draft":
        errors["status"] = "Only draft versions can be published."

    questions = list(
        version.questions.prefetch_related("options").filter(
            is_active=True
        )
    )

    for question in questions:
        try:
            validate_question(question)
        except ValidationError as exc:
            errors.setdefault("questions", []).append(
                f"{question.key}: {'; '.join(exc.messages)}"
            )

    dependency_errors = validate_question_dependencies(questions)

    if dependency_errors:
        errors.setdefault("questions", []).extend(
            dependency_errors
        )

    if errors:
        raise ValidationError(errors)

    return True


@transaction.atomic
def publish_product_draft(
    configuration_id,
    organization_id,
    actor=None,
):
    """
    Atomically publish a validated product conversation draft.
    """

    configuration = (
        ProductConversationConfiguration.objects
        .select_for_update()
        .get(
            pk=configuration_id,
            organization_id=organization_id,
        )
    )

    if not configuration.is_enabled:
        raise ValidationError(
            "This product conversation configuration is disabled."
        )

    product = get_eligible_whatsapp_product(
        configuration.product_id,
        organization_id,
    )

    if not configuration.draft_version_id:
        raise ValidationError(
            "There is no product conversation draft to publish."
        )

    draft = (
        ProductConversationVersion.objects
        .select_for_update()
        .get(
            pk=configuration.draft_version_id,
            configuration=configuration,
            status="draft",
        )
    )

    validate_product_version_for_publish(draft)

    snapshot = build_product_version_snapshot(draft)
    now = timezone.now()

    previous_id = configuration.published_version_id

    if previous_id:
        previous = (
            ProductConversationVersion.objects
            .select_for_update()
            .get(
                pk=previous_id,
                configuration=configuration,
                status="published",
            )
        )

        ProductConversationVersion.objects.filter(
            pk=previous.pk,
            status="published",
        ).update(status="archived")

        record_product_configuration_audit(
            configuration=configuration,
            version=previous,
            actor=actor,
            action="archived",
            details={
                "version_number": previous.version_number,
            },
        )

    ProductConversationVersion.objects.filter(
        pk=draft.pk,
        status="draft",
    ).update(
        status="published",
        snapshot=snapshot,
        published_by=actor,
        published_at=now,
        updated_at=now,
    )

    configuration.published_version_id = draft.pk
    configuration.draft_version = None

    configuration.full_clean()
    configuration.save(
        update_fields=[
            "published_version",
            "draft_version",
            "updated_at",
        ]
    )

    record_product_configuration_audit(
        configuration=configuration,
        version=draft,
        actor=actor,
        action="published",
        details={
            "version_number": draft.version_number,
            "previous_version_id": previous_id,
            "published_at": now.isoformat(),
        },
    )

    return ProductConversationVersion.objects.get(pk=draft.pk)