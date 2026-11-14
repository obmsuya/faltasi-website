"""
Runtime for published Product Conversation Builder configurations.

This module deliberately does not send WhatsApp messages or execute
business transactions. It manages question progression and validated
answers only.
"""

import re
from decimal import Decimal, InvalidOperation

from conversation_builder.models import (
    ProductConversationConfiguration,
    ProductConversationVersion,
)


STATE_KEY = "product_conversation"
BUILDER_STEP = "whatsapp_product_builder"
BUILDER_WAITING_FOR = "product_conversation_question"


def _get_namespace(state):
    data = dict(state.data or {})
    namespace = data.get(STATE_KEY)

    if not isinstance(namespace, dict):
        namespace = {}

    return data, namespace


def _save_namespace(state, data, namespace):
    data[STATE_KEY] = namespace
    state.data = data
    state.save()


def _get_snapshot_version(state, organization, product):
    """
    Return the pinned version for an active conversation.

    Existing conversations may continue on an archived version.
    New conversations must use the currently enabled published version.
    """
    _, namespace = _get_namespace(state)

    version_id = namespace.get("version_id")
    configuration_id = namespace.get("configuration_id")

    if version_id and configuration_id:
        return (
            ProductConversationVersion.objects
            .filter(
                pk=version_id,
                configuration_id=configuration_id,
                configuration__organization_id=organization.pk,
                configuration__product_id=product.pk,
                status__in=("published", "archived"),
            )
            .first()
        )

    configuration = (
        ProductConversationConfiguration.objects
        .filter(
            organization_id=organization.pk,
            product_id=product.pk,
            is_enabled=True,
            published_version__status="published",
        )
        .select_related("published_version")
        .first()
    )

    if not configuration:
        return None

    return configuration.published_version


def start_product_conversation(state, organization, product):
    """
    Pin the latest enabled published version to this conversation.

    Returns the runtime result. Returns None when no enabled published
    configuration exists, allowing the legacy workflow to continue.
    """
    version = _get_snapshot_version(state, organization, product)

    if not version:
        return None

    data, namespace = _get_namespace(state)

    # Do not reset an existing conversation pinned to this same version.
    if (
        namespace.get("version_id") == version.pk
        and namespace.get("configuration_id") == version.configuration_id
    ):
        return get_runtime_status(state, organization, product)

    # A new product conversation gets a fresh, isolated answer namespace.
    namespace = {
        "configuration_id": version.configuration_id,
        "version_id": version.pk,
        "version_number": version.version_number,
        "answers": {},
        "skipped": [],
        "attempts": {},
        "status": "in_progress",
    }

    _save_namespace(state, data, namespace)

    state.current_step = BUILDER_STEP
    state.waiting_for = BUILDER_WAITING_FOR
    state.save()

    return get_runtime_status(state, organization, product)


def _question_is_visible(question, answers, skipped):
    """
    Current Builder dependency schema supports depends_on only.
    A dependency is satisfied when its question has been answered
    or explicitly skipped.
    """
    conditions = question.get("display_conditions") or {}
    dependencies = conditions.get("depends_on", [])

    if not isinstance(dependencies, list):
        return False

    completed_keys = set(answers) | set(skipped)

    return all(key in completed_keys for key in dependencies)


def get_next_question(snapshot, namespace):
    """
    Find the next active, visible, unanswered question.
    """
    questions = snapshot.get("questions", [])

    if not isinstance(questions, list):
        return None

    answers = namespace.get("answers") or {}
    skipped = namespace.get("skipped") or []

    ordered_questions = sorted(
        (
            question for question in questions
            if isinstance(question, dict)
            and question.get("is_active", True)
        ),
        key=lambda question: (
            question.get("order", 1),
            question.get("key", ""),
        ),
    )

    for question in ordered_questions:
        key = question.get("key")

        if not key or key in answers or key in skipped:
            continue

        if _question_is_visible(question, answers, skipped):
            return question

    return None


def get_runtime_status(state, organization, product):
    """
    Return the pinned snapshot and the next eligible question.
    """
    version = _get_snapshot_version(state, organization, product)

    if not version:
        return None

    snapshot = version.snapshot or {}

    if not isinstance(snapshot, dict):
        return None

    _, namespace = _get_namespace(state)

    if namespace.get("version_id") != version.pk:
        return None

    if namespace.get("status") == "completed":
        return {
            "status": "completed",
            "version": version,
            "snapshot": snapshot,
            "question": None,
            "namespace": namespace,
        }

    question = get_next_question(snapshot, namespace)

    if question is None:
        namespace["status"] = "completed"
        data, _ = _get_namespace(state)
        _save_namespace(state, data, namespace)

        return {
            "status": "completed",
            "version": version,
            "snapshot": snapshot,
            "question": None,
            "namespace": namespace,
        }

    return {
        "status": "in_progress",
        "version": version,
        "snapshot": snapshot,
        "question": question,
        "namespace": namespace,
    }


def validate_product_question_answer(question, raw_value):
    """
    Validate one answer using the rules stored in the published snapshot.

    Returns:
        (True, cleaned_value) for a valid answer.
        (False, None) for an invalid answer.
    """
    if raw_value is None or isinstance(raw_value, (dict, list, bool)):
        return False, None

    value = str(raw_value).strip()

    if not value:
        return False, None

    field_type = question.get("field_type")
    rules = question.get("validation_rules") or {}

    if not isinstance(rules, dict):
        return False, None

    if field_type == "text":
        minimum = rules.get("min_length")
        maximum = rules.get("max_length")

        if minimum is not None and len(value) < minimum:
            return False, None

        if maximum is not None and len(value) > maximum:
            return False, None

        return True, value

    if field_type == "number":
        try:
            number = Decimal(value)
        except (InvalidOperation, ValueError):
            return False, None

        if not number.is_finite():
            return False, None

        minimum = rules.get("min_value")
        maximum = rules.get("max_value")

        if minimum is not None and number < Decimal(str(minimum)):
            return False, None

        if maximum is not None and number > Decimal(str(maximum)):
            return False, None

        # Store JSON-compatible numeric values.
        if number == number.to_integral_value():
            return True, int(number)

        return True, float(number)

    if field_type == "yes_no":
        normalized = value.casefold()

        yes_values = {
            str(item).strip().casefold()
            for item in rules.get("yes_values", [])
        }
        no_values = {
            str(item).strip().casefold()
            for item in rules.get("no_values", [])
        }

        if normalized in yes_values:
            return True, "yes"

        if normalized in no_values:
            return True, "no"

        return False, None

    if field_type == "choice":
        options = question.get("options") or []

        for option in options:
            if not isinstance(option, dict) or not option.get("is_active", True):
                continue

            option_value = str(option.get("value", "")).strip()
            option_label = str(option.get("label", "")).strip()

            if value.casefold() in {
                option_value.casefold(),
                option_label.casefold(),
            }:
                return True, option_value

        return False, None

    return False, None



def submit_product_question_answers(
    state,
    organization,
    product,
    answers,
    *,
    corrections=None,
):
    """
    Validate and save multiple AI-extracted or directly supplied answers.

    Answers are processed in dependency order, regardless of the order
    in which the AI supplied them.
    """
    if not isinstance(answers, dict) or (
        corrections is not None and not isinstance(corrections, dict)
    ):
        return {
            "status": "invalid_input",
            "accepted": [],
            "corrected": [],
            "rejected": [],
        }

    corrections = corrections or {}
    runtime = get_runtime_status(state, organization, product)

    if not runtime or runtime["status"] != "in_progress":
        return {
            "status": "not_active",
            "accepted": [],
            "corrected": [],
            "rejected": [],
        }

    snapshot = runtime["snapshot"]
    data, namespace = _get_namespace(state)

    ordered_questions = sorted(
        (
            question for question in snapshot.get("questions", [])
            if isinstance(question, dict)
            and question.get("key")
            and question.get("is_active", True)
        ),
        key=lambda question: (
            question.get("order", 1),
            question.get("key", ""),
        ),
    )

    questions = {
        question["key"]: question
        for question in ordered_questions
    }

    stored_answers = dict(namespace.get("answers") or {})
    skipped = list(namespace.get("skipped") or [])
    attempts = dict(namespace.get("attempts") or {})

    accepted = []
    corrected = []
    rejected = []

    # Corrections are separate from new answers and can only update an
    # existing answer for an active, visible question in this pinned snapshot.
    for key, raw_value in corrections.items():
        question = questions.get(key)
        if (
            question is None
            or key not in stored_answers
            or key in skipped
            or not _question_is_visible(question, stored_answers, skipped)
        ):
            continue

        valid, cleaned_value = validate_product_question_answer(
            question,
            raw_value,
        )
        if valid:
            if stored_answers.get(key) != cleaned_value:
                stored_answers[key] = cleaned_value
                corrected.append(key)
        else:
            attempts[key] = int(attempts.get(key, 0)) + 1
            rejected.append({
                "key": key,
                "attempts": attempts[key],
                "max_attempts": question.get("max_attempts", 3),
                "attempts_exhausted": (
                    attempts[key] >= question.get("max_attempts", 3)
                ),
                "correction": True,
            })

    # Only process answers belonging to active, unanswered questions.
    pending = {
        key: value
        for key, value in answers.items()
        if key in questions
        and key not in stored_answers
        and key not in skipped
    }

    # Repeat while newly accepted parent answers make dependent
    # questions available.
    while pending:
        processed_any = False

        for question in ordered_questions:
            key = question["key"]

            if key not in pending:
                continue

            if not _question_is_visible(
                question,
                stored_answers,
                skipped,
            ):
                continue

            raw_value = pending.pop(key)
            processed_any = True

            valid, cleaned_value = validate_product_question_answer(
                question,
                raw_value,
            )

            if valid:
                stored_answers[key] = cleaned_value
                accepted.append(key)
            else:
                attempts[key] = int(attempts.get(key, 0)) + 1

                rejected.append({
                    "key": key,
                    "attempts": attempts[key],
                    "max_attempts": question.get("max_attempts", 3),
                    "attempts_exhausted": (
                        attempts[key] >= question.get("max_attempts", 3)
                    ),
                })

        # Remaining answers depend on a question that has not
        # successfully been completed.
        if not processed_any:
            break

    namespace["answers"] = stored_answers
    namespace["skipped"] = skipped
    namespace["attempts"] = attempts

    _save_namespace(state, data, namespace)

    runtime = get_runtime_status(state, organization, product)

    return {
        "status": runtime["status"] if runtime else "not_active",
        "accepted": accepted,
        "corrected": corrected,
        "rejected": rejected,
        "next_question": runtime["question"] if runtime else None,
        "namespace": runtime["namespace"] if runtime else namespace,
    }


def skip_product_question(state, organization, product, question_key):
    """
    Skip an optional question only when it is the currently available
    question and its published definition permits skipping.
    """
    runtime = get_runtime_status(state, organization, product)

    if not runtime or runtime["status"] != "in_progress":
        return {"status": "not_active"}

    question = next(
        (
            item for item in runtime["snapshot"].get("questions", [])
            if isinstance(item, dict)
            and item.get("key") == question_key
            and item.get("is_active", True)
        ),
        None,
    )

    if not question:
        return {"status": "question_not_found"}

    # A future or otherwise unavailable question cannot be skipped.
    current_question = runtime.get("question")

    if not current_question or current_question.get("key") != question_key:
        return {"status": "question_not_available"}

    if question.get("is_required", True) or not question.get("allow_skip", False):
        return {"status": "skip_not_allowed"}

    namespace = runtime["namespace"]
    skipped = list(namespace.get("skipped") or [])

    if question_key not in skipped:
        skipped.append(question_key)

    namespace["skipped"] = skipped

    data, _ = _get_namespace(state)
    _save_namespace(state, data, namespace)

    runtime = get_runtime_status(state, organization, product)

    return {
        "status": runtime["status"] if runtime else "not_active",
        "next_question": runtime["question"] if runtime else None,
        "namespace": runtime["namespace"] if runtime else namespace,
    }
