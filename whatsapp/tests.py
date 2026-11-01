
from unittest.mock import Mock, patch

from django.test import TestCase
from django.utils import timezone

from organizations.models import Organization
from customers.models import Customer

from whatsapp.models import (
    Conversation,
    Message,
    WhatsAppBusinessAccount,
    WhatsAppPhoneNumber,
)

from whatsapp.views import (
    process_whatsapp_marketing_consent,
    send_product_marketing_template,
)

class WhatsAppMarketingConsentTests(TestCase):

    def setUp(self):
        self.org_a = Organization.objects.create(
            name="Test Business A",
            organization_type="business",
            status="active",
        )

        self.org_b = Organization.objects.create(
            name="Test Business B",
            organization_type="business",
            status="active",
        )

        self.customer_a = Customer.objects.create(
            organization=self.org_a,
            name="Customer A",
            phone="255700000001",
        )

        self.customer_b = Customer.objects.create(
            organization=self.org_b,
            name="Customer B",
            phone="255700000001",
        )

    def test_yes_activates_marketing_consent(self):
        reply = process_whatsapp_marketing_consent(
            self.customer_a, "YES"
        )

        self.customer_a.refresh_from_db()

        self.assertTrue(self.customer_a.whatsapp_marketing_opt_in)
        self.assertIsNotNone(
            self.customer_a.whatsapp_marketing_opt_in_at
        )
        self.assertEqual(
            self.customer_a.whatsapp_marketing_opt_in_source,
            "whatsapp_reply",
        )
        self.assertIsNone(
            self.customer_a.whatsapp_marketing_opt_out_at
        )
        self.assertIsNotNone(reply)

    def test_stop_withdraws_marketing_consent(self):
        self.customer_a.whatsapp_marketing_opt_in = True
        self.customer_a.whatsapp_marketing_opt_in_at = timezone.now()
        self.customer_a.save()

        reply = process_whatsapp_marketing_consent(
            self.customer_a, "STOP"
        )

        self.customer_a.refresh_from_db()

        self.assertFalse(self.customer_a.whatsapp_marketing_opt_in)
        self.assertIsNotNone(
            self.customer_a.whatsapp_marketing_opt_out_at
        )
        self.assertIsNotNone(reply)

    def test_repeated_yes_preserves_original_opt_in_timestamp(self):
        process_whatsapp_marketing_consent(
            self.customer_a, "YES"
        )

        self.customer_a.refresh_from_db()
        original_timestamp = self.customer_a.whatsapp_marketing_opt_in_at

        process_whatsapp_marketing_consent(
            self.customer_a, "YES"
        )

        self.customer_a.refresh_from_db()

        self.assertEqual(
            self.customer_a.whatsapp_marketing_opt_in_at,
            original_timestamp,
        )

    def test_stop_does_not_affect_another_organization(self):
        process_whatsapp_marketing_consent(
            self.customer_b, "YES"
        )

        process_whatsapp_marketing_consent(
            self.customer_a, "STOP"
        )

        self.customer_a.refresh_from_db()
        self.customer_b.refresh_from_db()

        self.assertFalse(self.customer_a.whatsapp_marketing_opt_in)
        self.assertTrue(self.customer_b.whatsapp_marketing_opt_in)

    def test_unrecognized_message_does_not_change_consent(self):
        reply = process_whatsapp_marketing_consent(
            self.customer_a, "Hello"
        )

        self.customer_a.refresh_from_db()

        self.assertIsNone(reply)
        self.assertFalse(self.customer_a.whatsapp_marketing_opt_in)
        self.assertIsNone(
            self.customer_a.whatsapp_marketing_opt_in_at
        )



class WhatsAppProductMarketingTemplateTests(TestCase):

    def setUp(self):
        self.org_a = Organization.objects.create(
            name="Marketing Test Business A",
            organization_type="business",
            status="active",
        )

        self.org_b = Organization.objects.create(
            name="Marketing Test Business B",
            organization_type="business",
            status="active",
        )

        self.customer = Customer.objects.create(
            organization=self.org_a,
            name="Marketing Customer",
            phone="255700000010",
            whatsapp_marketing_opt_in=True,
            whatsapp_marketing_opt_in_at=timezone.now(),
            whatsapp_marketing_opt_in_source="whatsapp_reply",
        )

        self.waba_a = WhatsAppBusinessAccount.objects.create(
            organization=self.org_a,
            waba_id="TEST_WABA_A",
            business_name="Business A",
        )

        self.phone_a = WhatsAppPhoneNumber.objects.create(
            organization=self.org_a,
            whatsapp_business_account=self.waba_a,
            phone_number_id="TEST_PHONE_ID_A",
            phone_number="255700000020",
        )

        self.conversation = Conversation.objects.create(
            organization=self.org_a,
            whatsapp_phone_number=self.phone_a,
            customer=self.customer,
            phone_number=self.customer.phone,
            status="active",
        )

    @patch("whatsapp.views.send_whatsapp_template")
    def test_opted_in_customer_receives_template(self, mock_send):

        response = Mock()
        response.status_code = 200
        response.json.return_value = {
            "messages": [{"id": "wamid.test.template.001"}]
        }
        mock_send.return_value = response

        result = send_product_marketing_template(
            customer=self.customer,
            whatsapp_phone=self.phone_a,
            phone_number=self.customer.phone,
            conversation=self.conversation,
            incoming_message_id="wamid.incoming.001",
        )

        self.assertTrue(result)
        mock_send.assert_called_once()

        saved_message = Message.objects.get(
            whatsapp_message_id="wamid.test.template.001"
        )

        self.assertEqual(saved_message.organization, self.org_a)
        self.assertEqual(saved_message.conversation, self.conversation)
        self.assertEqual(
            saved_message.metadata["template_name"],
            "product_enquiry_response",
        )

    @patch("whatsapp.views.send_whatsapp_template")
    def test_customer_without_consent_does_not_receive_template(
        self, mock_send
    ):

        self.customer.whatsapp_marketing_opt_in = False
        self.customer.save()

        result = send_product_marketing_template(
            customer=self.customer,
            whatsapp_phone=self.phone_a,
            phone_number=self.customer.phone,
            conversation=self.conversation,
            incoming_message_id="wamid.incoming.002",
        )

        self.assertFalse(result)
        mock_send.assert_not_called()

    @patch("whatsapp.views.send_whatsapp_template")
    def test_duplicate_incoming_message_does_not_send_template(
        self, mock_send
    ):

        Message.objects.create(
            organization=self.org_a,
            conversation=self.conversation,
            direction="outgoing",
            sender_type="faltasi",
            message_type="text",
            content="Marketing template: product_enquiry_response",
            delivery_status="sent",
            metadata={
                "template_name": "product_enquiry_response",
                "triggered_by_incoming_message_id": "wamid.incoming.003",
            },
        )

        result = send_product_marketing_template(
            customer=self.customer,
            whatsapp_phone=self.phone_a,
            phone_number=self.customer.phone,
            conversation=self.conversation,
            incoming_message_id="wamid.incoming.003",
        )

        self.assertFalse(result)
        mock_send.assert_not_called()

    @patch("whatsapp.views.send_whatsapp_template")
    def test_organization_mismatch_blocks_template(self, mock_send):

        waba_b = WhatsAppBusinessAccount.objects.create(
            organization=self.org_b,
            waba_id="TEST_WABA_B",
            business_name="Business B",
        )

        phone_b = WhatsAppPhoneNumber.objects.create(
            organization=self.org_b,
            whatsapp_business_account=waba_b,
            phone_number_id="TEST_PHONE_ID_B",
            phone_number="255700000030",
        )

        result = send_product_marketing_template(
            customer=self.customer,
            whatsapp_phone=phone_b,
            phone_number=self.customer.phone,
            conversation=self.conversation,
            incoming_message_id="wamid.incoming.004",
        )

        self.assertFalse(result)
        mock_send.assert_not_called()

    @patch("whatsapp.views.send_whatsapp_template")
    def test_failed_meta_response_is_not_logged_as_sent(
        self, mock_send
    ):

        response = Mock()
        response.status_code = 400
        response.text = '{"error": "Test failure"}'
        mock_send.return_value = response

        result = send_product_marketing_template(
            customer=self.customer,
            whatsapp_phone=self.phone_a,
            phone_number=self.customer.phone,
            conversation=self.conversation,
            incoming_message_id="wamid.incoming.005",
        )

        self.assertFalse(result)

        self.assertFalse(
            Message.objects.filter(
                conversation=self.conversation,
                metadata__triggered_by_incoming_message_id=(
                    "wamid.incoming.005"
                ),
            ).exists()
        )
