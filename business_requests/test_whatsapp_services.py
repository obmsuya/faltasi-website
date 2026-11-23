from types import SimpleNamespace

from django.test import SimpleTestCase

from business_requests.services.whatsapp import validate_request_field_value


class RequestFieldValidationConfigurationTests(SimpleTestCase):
    def field(self, field_type, rules=None):
        return SimpleNamespace(
            field_type=field_type,
            validation_rules=rules or {},
        )

    def test_yes_no_values_come_from_field_configuration(self):
        field = self.field(
            "yes_no",
            {
                "yes_values": ["ndiyo", "yes"],
                "no_values": ["hapana", "no"],
                "yes_phrases": ["i need installation"],
                "no_phrases": ["without installation"],
            },
        )

        self.assertEqual(validate_request_field_value(field, "NDIYO"), (True, True))
        self.assertEqual(validate_request_field_value(field, "hapana"), (True, False))
        self.assertEqual(validate_request_field_value(field, "I need installation"), (True, True))
        self.assertEqual(validate_request_field_value(field, "without installation"), (True, False))
        self.assertEqual(validate_request_field_value(field, "sawa kabisa"), (False, None))

    def test_choice_must_match_a_configured_option(self):
        field = self.field("choice", {"choices": ["Retail", "Wholesale"]})

        self.assertEqual(validate_request_field_value(field, "wholesale"), (True, "Wholesale"))
        self.assertEqual(validate_request_field_value(field, "Export"), (False, None))

    def test_number_uses_configured_bounds_and_number_words(self):
        field = self.field(
            "number",
            {"min": 1, "max": 20, "number_words": {"three": 3}},
        )

        self.assertEqual(validate_request_field_value(field, "3"), (True, 3))
        self.assertEqual(validate_request_field_value(field, "three"), (True, 3))
        self.assertEqual(validate_request_field_value(field, "about three units"), (True, 3))
        self.assertEqual(validate_request_field_value(field, "we need 3 units"), (True, 3))
        self.assertEqual(validate_request_field_value(field, "0"), (False, None))
        self.assertEqual(validate_request_field_value(field, "twenty one"), (False, None))

    def test_text_length_rules_are_configurable(self):
        field = self.field("text", {"min_length": 3, "max_length": 8})

        self.assertEqual(validate_request_field_value(field, "Area 1"), (True, "Area 1"))
        self.assertEqual(validate_request_field_value(field, "ab"), (False, None))
        self.assertEqual(validate_request_field_value(field, "too long value"), (False, None))

    def test_choice_without_configured_options_preserves_legacy_free_text(self):
        field = self.field("choice")
        self.assertEqual(validate_request_field_value(field, "custom option"), (True, "custom option"))

    def test_yes_no_without_configured_values_does_not_guess(self):
        field = self.field("yes_no")

        self.assertEqual(validate_request_field_value(field, "yes"), (False, None))
