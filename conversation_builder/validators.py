
from django.core.exceptions import ValidationError

SUPPORTED_LANGUAGES = {"en", "sw"}

QUESTION_VALIDATION_KEYS = {
    "text": {"min_length", "max_length"},
    "number": {"min_value", "max_value"},
    "yes_no": {"yes_values", "no_values"},
    "choice": set(),
}

VERSION_SETTING_KEYS = {
    "language",
    "handover",
    "operating_hours",
    "consent",
    "limits",
    "features",
}


def validate_translations(translations, label):
    if not isinstance(translations, dict):
        raise ValidationError(f"{label} translations must be an object.")

    for language, value in translations.items():
        if language not in SUPPORTED_LANGUAGES:
            raise ValidationError(
                f"{label} contains unsupported language: {language}."
            )
        if not isinstance(value, str):
            raise ValidationError(
                f"{label} translation for {language} must be text."
            )


def validate_question(question):
    errors = {}

    if question.max_attempts < 1:
        errors["max_attempts"] = "At least one attempt must be allowed."

    if question.is_required and question.allow_skip:
        errors["allow_skip"] = (
            "A required question cannot allow skipping."
        )

    rules = question.validation_rules or {}

    if not isinstance(rules, dict):
        errors["validation_rules"] = "Validation rules must be an object."
    else:
        allowed_keys = QUESTION_VALIDATION_KEYS.get(
            question.field_type, set()
        )
        unknown_keys = set(rules) - allowed_keys

        if unknown_keys:
            errors["validation_rules"] = (
                f"Unsupported rules for {question.field_type}: "
                f"{', '.join(sorted(unknown_keys))}."
            )

        if question.field_type == "text":
            minimum = rules.get("min_length")
            maximum = rules.get("max_length")

            if minimum is not None and (
                not isinstance(minimum, int) or minimum < 0
            ):
                errors["validation_rules"] = "Invalid min_length."

            if maximum is not None and (
                not isinstance(maximum, int) or maximum < 1
            ):
                errors["validation_rules"] = "Invalid max_length."

            if (
                isinstance(minimum, int)
                and isinstance(maximum, int)
                and minimum > maximum
            ):
                errors["validation_rules"] = (
                    "min_length cannot exceed max_length."
                )

        elif question.field_type == "number":
            minimum = rules.get("min_value")
            maximum = rules.get("max_value")

            if minimum is not None and not isinstance(minimum, (int, float)):
                errors["validation_rules"] = "Invalid min_value."

            if maximum is not None and not isinstance(maximum, (int, float)):
                errors["validation_rules"] = "Invalid max_value."

            if (
                isinstance(minimum, (int, float))
                and isinstance(maximum, (int, float))
                and minimum > maximum
            ):
                errors["validation_rules"] = (
                    "min_value cannot exceed max_value."
                )

        elif question.field_type == "yes_no":
            for key in ("yes_values", "no_values"):
                values = rules.get(key, [])
                if not isinstance(values, list) or not all(
                    isinstance(value, str) and value.strip()
                    for value in values
                ):
                    errors["validation_rules"] = (
                        f"{key} must be a list of non-empty strings."
                    )

            yes_values = {
                value.strip().casefold()
                for value in rules.get("yes_values", [])
                if isinstance(value, str)
            }
            no_values = {
                value.strip().casefold()
                for value in rules.get("no_values", [])
                if isinstance(value, str)
            }

            if yes_values & no_values:
                errors["validation_rules"] = (
                    "Yes and no values cannot overlap."
                )

    try:
        validate_translations(question.translations or {}, "Question")
    except ValidationError as exc:
        errors["translations"] = exc.messages

    if not isinstance(question.display_conditions, dict):
        errors["display_conditions"] = (
            "Display conditions must be an object."
        )

    if question.field_type == "choice":
        if not question.pk or not question.options.filter(
            is_active=True
        ).exists():
            errors["field_type"] = (
                "A choice question needs at least one active option."
            )

    if errors:
        raise ValidationError(errors)



def validate_question_dependencies(questions):
    """
    Validate question references and detect circular dependencies.

    Supported format:
    {
        "depends_on": ["question_key"]
    }
    """
    errors = []
    question_keys = {question.key for question in questions}
    dependency_graph = {}

    for question in questions:
        conditions = question.display_conditions or {}

        if not isinstance(conditions, dict):
            errors.append(
                f"{question.key}: display_conditions must be an object."
            )
            dependency_graph[question.key] = []
            continue

        unknown_keys = set(conditions) - {"depends_on"}

        if unknown_keys:
            errors.append(
                f"{question.key}: unsupported display conditions: "
                f"{', '.join(sorted(unknown_keys))}."
            )

        references = conditions.get("depends_on", [])

        if not isinstance(references, list):
            errors.append(
                f"{question.key}: depends_on must be a list."
            )
            dependency_graph[question.key] = []
            continue

        dependencies = []
        seen = set()

        for reference in references:
            if not isinstance(reference, str) or reference not in question_keys:
                errors.append(
                    f"{question.key}: invalid dependency {reference!r}."
                )
                continue

            if reference == question.key:
                errors.append(
                    f"{question.key}: a question cannot depend on itself."
                )
                continue

            if reference in seen:
                errors.append(
                    f"{question.key}: duplicate dependency {reference!r}."
                )
                continue

            seen.add(reference)
            dependencies.append(reference)

        dependency_graph[question.key] = dependencies

    # Detect circular dependencies.
    visiting = set()
    visited = set()

    def visit(key, path):
        if key in visiting:
            cycle_start = path.index(key)
            cycle = path[cycle_start:] + [key]
            errors.append(
                "Circular question dependency: " + " -> ".join(cycle)
            )
            return

        if key in visited:
            return

        visiting.add(key)

        for dependency in dependency_graph.get(key, []):
            visit(dependency, path + [dependency])

        visiting.remove(key)
        visited.add(key)

    for key in dependency_graph:
        if key not in visited:
            visit(key, [key])

    return errors



def validate_version_for_publish(version):
    """
    Validate the complete draft before it can become active.

    This function does not publish or modify the version.
    """
    errors = {}

    if version.status != "draft":
        errors["status"] = "Only draft versions can be published."

    if not isinstance(version.settings, dict):
        errors["settings"] = "Settings must be an object."
    else:
        unknown_settings = set(version.settings) - VERSION_SETTING_KEYS
        if unknown_settings:
            errors["settings"] = (
                "Unsupported settings sections: "
                + ", ".join(sorted(unknown_settings))
            )

    if not isinstance(version.snapshot, dict):
        errors["snapshot"] = "Snapshot must be an object."

    questions = list(
        version.questions.prefetch_related("options").filter(is_active=True)
    )

    keys = set()

    for question in questions:
        if question.key in keys:
            errors.setdefault("questions", []).append(
                f"Duplicate question key: {question.key}."
            )
        keys.add(question.key)

        try:
            validate_question(question)
        except ValidationError as exc:
            errors.setdefault("questions", []).append(
                f"{question.key}: {'; '.join(exc.messages)}"
            )

    # Conditions use question keys, so references must resolve within
    # this version. The condition evaluator will enforce the full schema.
    for question in questions:
        conditions = question.display_conditions or {}
        references = conditions.get("depends_on", [])

        if not isinstance(references, list):
            errors.setdefault("questions", []).append(
                f"{question.key}: depends_on must be a list."
            )
            continue

        for reference in references:
            if not isinstance(reference, str) or reference not in keys:
                errors.setdefault("questions", []).append(
                    f"{question.key}: invalid dependency {reference!r}."
                )

    category_rules = version.category_rules.select_related(
        "category"
    ).filter(is_enabled=True)

    for rule in category_rules:
        if rule.category.organization_id != version.configuration.organization_id:
            errors.setdefault("categories", []).append(
                f"Category {rule.category_id} belongs to another organization."
            )

    if errors:
        raise ValidationError(errors)

    return True
