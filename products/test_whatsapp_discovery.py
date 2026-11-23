from types import SimpleNamespace

from django.test import SimpleTestCase

from products.services.public_data import clean_public_product_data
from products.services.whatsapp_discovery import classify_product_discovery_response


class ProductDiscoveryConfigurationTests(SimpleTestCase):
    def setUp(self):
        self.configuration = SimpleNamespace(
            yes_phrases=["yes please", "ndiyo"],
            no_phrases=["no thanks", "hapana"],
        )

    def test_yes_and_no_responses_use_configured_phrases(self):
        self.assertEqual(
            classify_product_discovery_response("NDIYO!", self.configuration),
            "yes",
        )
        self.assertEqual(
            classify_product_discovery_response("no thanks", self.configuration),
            "no",
        )

    def test_unconfigured_phrase_is_not_assumed_to_be_yes_or_no(self):
        self.assertIsNone(
            classify_product_discovery_response("sure", self.configuration)
        )

    def test_missing_configuration_does_not_guess(self):
        self.assertIsNone(classify_product_discovery_response("yes", None))


class PublicProductDataSanitizationTests(SimpleTestCase):
    def test_internal_financial_and_supplier_fields_are_removed_recursively(self):
        data = {
            "colour": "blue",
            "cost_price": 100,
            "supplier": "Internal Supplier",
            "details": {"profit_margin": 20, "size": "large"},
        }

        self.assertEqual(
            clean_public_product_data(data),
            {"colour": "blue", "details": {"size": "large"}},
        )
