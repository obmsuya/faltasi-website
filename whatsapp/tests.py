
import json
from types import SimpleNamespace
from unittest.mock import Mock, patch

from django.utils import timezone

from organizations.models import Organization
from customers.models import Customer
from whatsapp.views import customer_phone_allows_whatsapp
from django.test import TestCase, RequestFactory, override_settings


from whatsapp.models import (
    Conversation,
    Message,
    WhatsAppBusinessAccount,
    WhatsAppPhoneNumber,
)

from whatsapp.views import (
    process_whatsapp_marketing_consent,
    send_product_marketing_template,
    webhook,
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
            phone="+255700000001",
        )

        self.customer_b = Customer.objects.create(
            organization=self.org_b,
            name="Customer B",
            phone="+255700000001",
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


    def test_no_declines_marketing_invitation(self):
        reply = process_whatsapp_marketing_consent(
            self.customer_a, "NO"
        )

        self.customer_a.refresh_from_db()

        self.assertFalse(
            self.customer_a.whatsapp_marketing_opt_in
        )
        self.assertIsNotNone(
            self.customer_a.whatsapp_marketing_declined_at
        )
        self.assertIsNone(
            self.customer_a.whatsapp_marketing_opt_out_at
        )
        self.assertIsNotNone(reply)

    def test_no_does_not_unsubscribe_existing_customer(self):
        self.customer_a.whatsapp_marketing_opt_in = True
        self.customer_a.whatsapp_marketing_opt_in_at = timezone.now()
        self.customer_a.whatsapp_marketing_opt_in_source = "whatsapp_reply"
        self.customer_a.save()

        reply = process_whatsapp_marketing_consent(
            self.customer_a, "NO"
        )

        self.customer_a.refresh_from_db()

        self.assertTrue(
            self.customer_a.whatsapp_marketing_opt_in
        )
        self.assertIsNone(
            self.customer_a.whatsapp_marketing_opt_out_at
        )
        self.assertIsNone(
            self.customer_a.whatsapp_marketing_declined_at
        )
        self.assertIsNotNone(reply)

    def test_yes_clears_previous_decline(self):
        self.customer_a.whatsapp_marketing_declined_at = timezone.now()
        self.customer_a.save()

        process_whatsapp_marketing_consent(
            self.customer_a, "YES"
        )

        self.customer_a.refresh_from_db()

        self.assertTrue(
            self.customer_a.whatsapp_marketing_opt_in
        )
        self.assertIsNone(
            self.customer_a.whatsapp_marketing_declined_at
        )


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



class WhatsAppSenderSecurityTests(TestCase):

    def setUp(self):
        self.org_a = Organization.objects.create(
            name="Faltasi Test",
            organization_type="platform_owner",
            status="active",
        )

        self.org_b = Organization.objects.create(
            name="Merrylight Test",
            organization_type="business",
            status="active",
        )

        self.waba_b = WhatsAppBusinessAccount.objects.create(
            organization=self.org_b,
            waba_id="SECURITY_TEST_WABA_B",
            business_name="Merrylight WABA",
            status="connected",
            is_active=True,
        )

        self.phone_b = WhatsAppPhoneNumber.objects.create(
            organization=self.org_b,
            whatsapp_business_account=self.waba_b,
            phone_number_id="SECURITY_TEST_PHONE_B",
            phone_number="255700000099",
            status="connected",
            is_active=True,
        )

        self.customer = Customer.objects.create(
            organization=self.org_b,
            name="Merrylight Test Customer",
            phone="+255700000222",
            status="active",
            phone_status="active",
        )

    @override_settings(
        DEBUG=True,
        WHATSAPP_ACCESS_TOKEN="FALTASI_GLOBAL_TEST_TOKEN",
        WHATSAPP_PHONE_NUMBER_ID="FALTASI_GLOBAL_TEST_PHONE",
    )
    @patch("requests.post")
    def test_tenant_cannot_use_faltasi_global_credentials(
        self, mock_post
    ):
        from whatsapp.views import send_whatsapp_message

        result = send_whatsapp_message(
            whatsapp_phone=self.phone_b,
            phone_number="+255700000001",
            message="Security test",
        )

        self.assertIsNone(result)
        mock_post.assert_not_called()

    @override_settings(
        DEBUG=True,
        WHATSAPP_ACCESS_TOKEN="FALTASI_GLOBAL_TEST_TOKEN",
    )
    @patch("requests.post")
    def test_phone_with_mismatched_waba_is_blocked(
        self, mock_post
    ):
        from whatsapp.views import send_whatsapp_message

        self.phone_b.whatsapp_business_account = (
            WhatsAppBusinessAccount.objects.create(
                organization=self.org_a,
                waba_id="SECURITY_TEST_WABA_A",
                business_name="Faltasi WABA",
                status="connected",
                is_active=True,
            )
        )
        self.phone_b.save()

        result = send_whatsapp_message(
            whatsapp_phone=self.phone_b,
            phone_number="255700000001",
            message="Security test",
        )

        self.assertIsNone(result)
        mock_post.assert_not_called()

    @override_settings(
        DEBUG=True,
        WHATSAPP_ACCESS_TOKEN="FALTASI_GLOBAL_TEST_TOKEN",
    )
    @patch("requests.post")
    def test_disconnected_waba_cannot_send(
        self, mock_post
    ):
        from whatsapp.views import send_whatsapp_message

        self.waba_b.status = "disconnected"
        self.waba_b.save(update_fields=["status"])

        result = send_whatsapp_message(
            whatsapp_phone=self.phone_b,
            phone_number="+255700000001",
            message="Security test",
        )

        self.assertIsNone(result)
        mock_post.assert_not_called()

    @override_settings(
        DEBUG=True,
        WHATSAPP_ACCESS_TOKEN="FALTASI_GLOBAL_TEST_TOKEN",
    )
    @patch("requests.post")
    def test_inactive_phone_cannot_send(
        self, mock_post
    ):
        from whatsapp.views import send_whatsapp_message

        self.phone_b.is_active = False
        self.phone_b.save(update_fields=["is_active"])

        result = send_whatsapp_message(
            whatsapp_phone=self.phone_b,
            phone_number="+255700000001",
            message="Security test",
        )

        self.assertIsNone(result)
        mock_post.assert_not_called()

    def test_active_customer_phone_allows_whatsapp(self):
        self.assertTrue(
            customer_phone_allows_whatsapp(self.phone_b, self.customer.phone)
        )

    def test_inactive_phone_blocks_outbound_whatsapp(self):
        self.customer.phone_status = "inactive"
        self.customer.save(update_fields=["phone_status"])
        self.assertFalse(
            customer_phone_allows_whatsapp(self.phone_b, self.customer.phone)
        )

    def test_blocked_phone_blocks_outbound_whatsapp(self):
        self.customer.phone_status = "blocked"
        self.customer.save(update_fields=["phone_status"])
        self.assertFalse(
            customer_phone_allows_whatsapp(self.phone_b, self.customer.phone)
        )

    def test_inactive_customer_blocks_outbound_whatsapp(self):
        self.customer.status = "inactive"
        self.customer.save(update_fields=["status"])
        self.assertFalse(
            customer_phone_allows_whatsapp(self.phone_b, self.customer.phone)
        )

    def test_removed_phone_is_blocked_by_conversation_history(self):
        old_phone = self.customer.phone
        Conversation.objects.create(
            organization=self.org_b,
            whatsapp_phone_number=self.phone_b,
            customer=self.customer,
            phone_number=old_phone,
            status="active",
        )
        self.customer.phone = ""
        self.customer.phone_status = "removed"
        self.customer.save(update_fields=["phone", "phone_status"])
        self.assertFalse(
            customer_phone_allows_whatsapp(self.phone_b, old_phone)
        )

    def test_unknown_recipient_retains_existing_behavior(self):
        self.assertTrue(
            customer_phone_allows_whatsapp(self.phone_b, "+255700000999")
        )

    def test_other_organization_phone_status_does_not_block_recipient(self):
        Customer.objects.create(
            organization=self.org_a,
            name="Different Organization Customer",
            phone=self.customer.phone,
            status="active",
            phone_status="blocked",
        )
        self.assertTrue(
            customer_phone_allows_whatsapp(self.phone_b, self.customer.phone)
        )


class WhatsAppMarketingInvitationWebhookTests(TestCase):

    def setUp(self):
        self.factory = RequestFactory()

        self.organization = Organization.objects.create(
            name="Invitation Test Business",
            organization_type="business",
            status="active",
        )

        self.waba = WhatsAppBusinessAccount.objects.create(
            organization=self.organization,
            waba_id="TEST_INVITATION_WABA",
            business_name="Invitation Test Business",
            status="connected",
            is_active=True,
        )

        self.whatsapp_phone = WhatsAppPhoneNumber.objects.create(
            whatsapp_business_account=self.waba,
            organization=self.organization,
            phone_number_id="TEST_INVITATION_PHONE_ID",
            phone_number="+255700000010",
            status="connected",
            is_active=True,
        )

    def create_customer(self, **kwargs):
        defaults = {
            "organization": self.organization,
            "name": "Invitation Test Customer",
            "phone": "+255700000001",
            "status": "active",
            "phone_status": "active",
            "relationship_stage": "visitor",
            "contact_source": "whatsapp",
        }
        defaults.update(kwargs)

        return Customer.objects.create(**defaults)

    def send_webhook_message(self, message_id, response):
        payload = {
            "object": "whatsapp_business_account",
            "entry": [
                {
                    "id": "TEST_INVITATION_WABA",
                    "changes": [
                        {
                            "field": "messages",
                            "value": {
                                "messaging_product": "whatsapp",
                                "metadata": {
                                    "display_phone_number": "255700000010",
                                    "phone_number_id": "TEST_INVITATION_PHONE_ID",
                                },
                                "messages": [
                                    {
                                        "from": "+255700000001",
                                        "id": message_id,
                                        "timestamp": "1794000000",
                                        "type": "text",
                                        "text": {
                                            "body": "Hello"
                                        },
                                    }
                                ],
                            },
                        }
                    ],
                }
            ],
        }

        request = self.factory.post(
            "/whatsapp/webhook/",
            data=__import__("json").dumps(payload),
            content_type="application/json",
        )

        with patch(
            "whatsapp.views.verify_meta_webhook_signature",
            return_value=True,
        ), patch(
            "whatsapp.views.handle_whatsapp_product_conversation",
            return_value=None,
        ), patch(
            "whatsapp.views.get_ai_product_reply",
            return_value=None,
        ), patch(
            "whatsapp.views.get_ai_general_interpretation",
            return_value={
                "action": "route_existing",
                "intent": "unclear",
                "answer": "",
            },
        ), patch(
            "whatsapp.views.get_ai_product_discovery_reply",
            return_value=None,
        ), patch(
            "whatsapp.views.find_request_category",
            return_value=None,
        ), patch(
            "whatsapp.views.search_whatsapp_products",
            return_value=None,
        ), patch(
            "whatsapp.views.process_customer_message",
            return_value="Thank you for contacting us.",
        ), patch(
            "whatsapp.views.send_whatsapp_message",
            return_value=response,
        ) as mock_send:

            webhook_response = webhook(request)

        return webhook_response, mock_send

    def successful_meta_response(self):
        response = Mock()
        response.status_code = 200
        response.text = ""
        response.json.return_value = {
            "messages": [
                {"id": "wamid.test_outgoing"}
            ]
        }
        return response

    def failed_meta_response(self):
        response = Mock()
        response.status_code = 400
        response.text = "Test WhatsApp send failure"
        return response

    def test_first_contact_receives_invitation_and_timestamp_is_recorded(self):
        response, mock_send = self.send_webhook_message(
            "wamid.test_incoming_001",
            self.successful_meta_response(),
        )

        self.assertEqual(response.status_code, 200)

        customer = Customer.objects.get(
            organization=self.organization,
            phone="+255700000001",
        )

        self.assertEqual(customer.relationship_stage, "visitor")
        self.assertFalse(customer.whatsapp_marketing_opt_in)

        self.assertIsNotNone(
            customer.whatsapp_marketing_invitation_sent_at
        )

        self.assertEqual(
            customer.marketing_consent_status,
            "pending",
        )

        mock_send.assert_called_once()

        sent_reply = mock_send.call_args.args[2]

        self.assertIn(
            "Pia tuna bidhaa nyingi ambazo nina uhakika utazifurahia",
            sent_reply,
        )

        self.assertIn("Nijibu YES kukubali au NO kukataa.", sent_reply)

        self.assertIn(
            "Thank you for contacting us.",
            sent_reply,
        )

        outgoing_message = Message.objects.get(
            organization=self.organization,
            whatsapp_message_id="wamid.test_outgoing",
        )

        self.assertIn(
            "Nijibu YES kukubali au NO kukataa.",
            outgoing_message.content,
        )

    def test_english_organization_receives_english_invitation(self):
        self.organization.language = "en"
        self.organization.save(update_fields=["language"])

        response, mock_send = self.send_webhook_message(
            "wamid.test_incoming_english",
            self.successful_meta_response(),
        )

        self.assertEqual(response.status_code, 200)
        mock_send.assert_called_once()

        sent_reply = mock_send.call_args.args[2]

        self.assertIn(
            "Would you like to receive WhatsApp marketing messages?",
            sent_reply,
        )
        self.assertIn(
            "Reply YES to subscribe or NO to decline.",
            sent_reply,
        )

        customer = Customer.objects.get(
            organization=self.organization,
            phone="+255700000001",
        )

        self.assertIsNotNone(
            customer.whatsapp_marketing_invitation_sent_at
        )

    def test_failed_whatsapp_send_does_not_record_invitation(self):
        response, mock_send = self.send_webhook_message(
            "wamid.test_incoming_002",
            self.failed_meta_response(),
        )

        self.assertEqual(response.status_code, 200)

        customer = Customer.objects.get(
            organization=self.organization,
            phone="+255700000001",
        )

        self.assertIsNone(
            customer.whatsapp_marketing_invitation_sent_at
        )

        self.assertEqual(
            customer.marketing_consent_status,
            "not_asked",
        )

        mock_send.assert_called_once()

        self.assertFalse(
            Message.objects.filter(
                organization=self.organization,
                whatsapp_message_id="wamid.test_outgoing",
            ).exists()
        )

    def test_existing_invitation_is_not_sent_again(self):
        customer = self.create_customer(
            whatsapp_marketing_invitation_sent_at=timezone.now(),
        )

        response, mock_send = self.send_webhook_message(
            "wamid.test_incoming_003",
            self.successful_meta_response(),
        )

        self.assertEqual(response.status_code, 200)

        customer.refresh_from_db()

        self.assertIsNotNone(
            customer.whatsapp_marketing_invitation_sent_at
        )

        sent_reply = mock_send.call_args.args[2]

        self.assertNotIn(
            "Would you like to receive WhatsApp marketing",
            sent_reply,
        )

        self.assertEqual(
            Message.objects.filter(
                organization=self.organization,
                direction="outgoing",
            ).count(),
            1,
        )

    def test_declined_customer_does_not_receive_another_invitation(self):
        customer = self.create_customer(
            whatsapp_marketing_declined_at=timezone.now(),
        )

        response, mock_send = self.send_webhook_message(
            "wamid.test_incoming_004",
            self.successful_meta_response(),
        )

        self.assertEqual(response.status_code, 200)

        customer.refresh_from_db()

        self.assertIsNotNone(
            customer.whatsapp_marketing_declined_at
        )

        sent_reply = mock_send.call_args.args[2]

        self.assertNotIn(
            "Would you like to receive WhatsApp marketing",
            sent_reply,
        )

    def test_unsubscribed_customer_does_not_receive_another_invitation(self):
        customer = self.create_customer(
            whatsapp_marketing_opt_out_at=timezone.now(),
        )

        response, mock_send = self.send_webhook_message(
            "wamid.test_incoming_005",
            self.successful_meta_response(),
        )

        self.assertEqual(response.status_code, 200)

        customer.refresh_from_db()

        self.assertIsNotNone(
            customer.whatsapp_marketing_opt_out_at
        )

        sent_reply = mock_send.call_args.args[2]

        self.assertNotIn(
            "Would you like to receive WhatsApp marketing",
            sent_reply,
        )

    def test_inactive_customer_does_not_receive_invitation(self):
        customer = self.create_customer(
            status="inactive",
        )

        response, mock_send = self.send_webhook_message(
            "wamid.test_incoming_006",
            self.successful_meta_response(),
        )

        self.assertEqual(response.status_code, 200)

        sent_reply = mock_send.call_args.args[2]

        self.assertNotIn(
            "Would you like to receive WhatsApp marketing",
            sent_reply,
        )

        customer.refresh_from_db()

        self.assertIsNone(
            customer.whatsapp_marketing_invitation_sent_at
        )

    def test_blocked_phone_does_not_receive_invitation(self):
        customer = self.create_customer(
            phone_status="blocked",
        )

        response, mock_send = self.send_webhook_message(
            "wamid.test_incoming_007",
            self.successful_meta_response(),
        )

        self.assertEqual(response.status_code, 200)

        sent_reply = mock_send.call_args.args[2]

        self.assertNotIn(
            "Would you like to receive WhatsApp marketing",
            sent_reply,
        )

        customer.refresh_from_db()

        self.assertIsNone(
            customer.whatsapp_marketing_invitation_sent_at
        )

    def test_same_phone_in_another_organization_is_isolated(self):
        other_organization = Organization.objects.create(
            name="Other Invitation Business",
            organization_type="business",
            status="active",
        )

        other_customer = Customer.objects.create(
            organization=other_organization,
            name="Other Organization Customer",
            phone="+255700000001",
            status="active",
            phone_status="active",
            whatsapp_marketing_opt_in=True,
            whatsapp_marketing_opt_in_at=timezone.now(),
        )

        response, mock_send = self.send_webhook_message(
            "wamid.test_incoming_008",
            self.successful_meta_response(),
        )

        self.assertEqual(response.status_code, 200)

        local_customer = Customer.objects.get(
            organization=self.organization,
            phone="+255700000001",
        )

        other_customer.refresh_from_db()

        self.assertNotEqual(
            local_customer.id,
            other_customer.id,
        )

        self.assertIsNotNone(
            local_customer.whatsapp_marketing_invitation_sent_at
        )

        self.assertTrue(
            other_customer.whatsapp_marketing_opt_in
        )

        self.assertIsNotNone(
            other_customer.whatsapp_marketing_opt_in_at
        )

        sent_reply = mock_send.call_args.args[2]

        self.assertIn(
            "Pia tuna bidhaa nyingi ambazo nina uhakika utazifurahia",
            sent_reply,
        )

class WhatsAppCanonicalProductSearchTests(TestCase):
    """Tests for the WhatsApp adapter using canonical product search."""

    def setUp(self):
        from products.models import Product
        from whatsapp.models import ConversationState

        self.Product = Product
        self.ConversationState = ConversationState

        self.organization = Organization.objects.create(
            name="Canonical Search Business",
            organization_type="business",
            status="active",
        )

        self.other_organization = Organization.objects.create(
            name="Other Search Business",
            organization_type="business",
            status="active",
        )

        self.customer = Customer.objects.create(
            organization=self.organization,
            name="Search Customer",
            phone="+255700000101",
        )

        self.conversation = Conversation.objects.create(
            organization=self.organization,
            customer=self.customer,
            phone_number="+255700000101",
        )

        self.state = ConversationState.objects.create(
            conversation=self.conversation,
            current_step="previous_step",
            waiting_for="previous_input",
            data={
                "selected_whatsapp_product_id": 999,
                "selected_whatsapp_product_name": "Old Product",
                "whatsapp_product_quantity": 2,
                "whatsapp_product_action": "buy",
                "unrelated_value": "preserve_me",
            },
        )

    def create_product(self, name, organization=None, **kwargs):
        return self.Product.objects.create(
            organization=organization or self.organization,
            name=name,
            price=kwargs.pop("price", "25000.00"),
            **kwargs,
        )

    def search_result(self, product):
        return {"id": product.pk}

    def test_uses_canonical_search_with_five_result_limit(self):
        from unittest.mock import patch
        from whatsapp.views import search_whatsapp_products

        products = [
            self.create_product(f"Laptop Model {number}")
            for number in range(1, 6)
        ]

        results = [self.search_result(product) for product in products]

        with patch(
            "whatsapp.views.search_organization_products",
            return_value=results,
        ) as canonical_search:
            reply = search_whatsapp_products(
                "laptop",
                self.organization,
                self.state,
            )

        canonical_search.assert_called_once_with(
            self.organization,
            "laptop",
            limit=5,
        )

        self.assertEqual(reply.count("   Price:"), 5)

    def test_preserves_canonical_ranking_and_updates_state(self):
        from unittest.mock import patch
        from whatsapp.views import search_whatsapp_products

        first = self.create_product(
            "Laptop Alpha",
            display_order=20,
        )
        second = self.create_product(
            "Laptop Beta",
            display_order=1,
        )

        with patch(
            "whatsapp.views.search_organization_products",
            return_value=[
                self.search_result(first),
                self.search_result(second),
            ],
        ):
            reply = search_whatsapp_products(
                "laptop",
                self.organization,
                self.state,
            )

        self.assertLess(
            reply.index("Laptop Alpha"),
            reply.index("Laptop Beta"),
        )

        self.state.refresh_from_db()

        self.assertEqual(
            self.state.data["whatsapp_product_ids"],
            [first.pk, second.pk],
        )
        self.assertEqual(
            self.state.current_step,
            "whatsapp_product_selection",
        )
        self.assertEqual(
            self.state.waiting_for,
            "product_selection",
        )

        self.assertNotIn(
            "selected_whatsapp_product_id",
            self.state.data,
        )
        self.assertNotIn(
            "selected_whatsapp_product_name",
            self.state.data,
        )
        self.assertNotIn(
            "whatsapp_product_quantity",
            self.state.data,
        )
        self.assertNotIn(
            "whatsapp_product_action",
            self.state.data,
        )
        self.assertEqual(
            self.state.data["unrelated_value"],
            "preserve_me",
        )

    def test_hydration_excludes_other_organizations_and_hidden_products(self):
        from unittest.mock import patch
        from whatsapp.views import search_whatsapp_products

        own_product = self.create_product("Laptop Own Business")

        foreign_product = self.create_product(
            "Laptop Foreign Business",
            organization=self.other_organization,
        )

        hidden_product = self.create_product(
            "Laptop Hidden Product",
            show_on_whatsapp=False,
        )

        results = [
            self.search_result(own_product),
            self.search_result(foreign_product),
            self.search_result(hidden_product),
        ]

        with patch(
            "whatsapp.views.search_organization_products",
            return_value=results,
        ):
            reply = search_whatsapp_products(
                "laptop",
                self.organization,
                self.state,
            )

        self.assertIn("Laptop Own Business", reply)
        self.assertNotIn("Laptop Foreign Business", reply)
        self.assertNotIn("Laptop Hidden Product", reply)

        self.state.refresh_from_db()
        self.assertEqual(
            self.state.data["whatsapp_product_ids"],
            [own_product.pk],
        )

    def test_no_results_returns_none_without_changing_state(self):
        from unittest.mock import patch
        from whatsapp.views import search_whatsapp_products

        original_data = dict(self.state.data)
        original_step = self.state.current_step
        original_waiting_for = self.state.waiting_for

        with patch(
            "whatsapp.views.search_organization_products",
            return_value=[],
        ) as canonical_search:
            reply = search_whatsapp_products(
                "unknown product",
                self.organization,
                self.state,
            )

        self.assertIsNone(reply)

        canonical_search.assert_called_once_with(
            self.organization,
            "unknown product",
            limit=5,
        )

        self.state.refresh_from_db()
        self.assertEqual(self.state.data, original_data)
        self.assertEqual(self.state.current_step, original_step)
        self.assertEqual(self.state.waiting_for, original_waiting_for)

    def test_empty_input_does_not_call_canonical_search(self):
        from unittest.mock import patch
        from whatsapp.views import search_whatsapp_products

        with patch(
            "whatsapp.views.search_organization_products",
        ) as canonical_search:
            self.assertIsNone(
                search_whatsapp_products(
                    "",
                    self.organization,
                    self.state,
                )
            )

            self.assertIsNone(
                search_whatsapp_products(
                    "laptop",
                    None,
                    self.state,
                )
            )

        canonical_search.assert_not_called()


class WhatsAppProductBuilderIntegrationTests(TestCase):
    """Integration tests for product-specific Builder in WhatsApp."""

    def setUp(self):
        from products.models import Product
        from whatsapp.models import ConversationState

        self.organization = Organization.objects.create(
            name="Builder Integration Business",
            organization_type="business",
            status="active",
        )

        self.customer = Customer.objects.create(
            organization=self.organization,
            name="Builder Test Customer",
            phone="+255700000201",
        )

        self.conversation = Conversation.objects.create(
            organization=self.organization,
            customer=self.customer,
            phone_number="+255700000201",
        )

        self.state = ConversationState.objects.create(
            conversation=self.conversation,
            current_step="whatsapp_product_selection",
            waiting_for="product_selection",
            data={},
        )

        self.product = Product.objects.create(
            organization=self.organization,
            name="Test Laptop",
            price="25000.00",
            is_active=True,
            show_on_whatsapp=True,
        )

    def publish_builder(self, questions):
        from conversation_builder.models import (
            ProductConversationQuestion,
        )
        from conversation_builder.services import (
            create_product_configuration,
            publish_product_draft,
        )

        configuration, draft = create_product_configuration(
            self.product.pk,
            self.organization.pk,
        )

        for question_data in questions:
            ProductConversationQuestion.objects.create(
                version=draft,
                **question_data,
            )

        publish_product_draft(
            configuration.pk,
            self.organization.pk,
        )

        return configuration

    def select_product(self):
        self.state.data = {
            **self.state.data,
            "whatsapp_product_ids": [self.product.pk],
        }
        self.state.current_step = "whatsapp_product_selection"
        self.state.waiting_for = "product_selection"
        self.state.save()

        from whatsapp.views import handle_whatsapp_product_conversation

        return handle_whatsapp_product_conversation(
            "1",
            self.organization,
            self.state,
        )

    def test_without_builder_preserves_legacy_quantity_prompt(self):
        response = self.select_product()

        self.assertEqual(
            response,
            (
                f"Asante! Umechagua {self.product.name}.\n\n"
                "Unahitaji kiasi gani? Tafadhali taja idadi unayohitaji."
            ),
        )

        self.state.refresh_from_db()

        self.assertEqual(
            self.state.current_step,
            "whatsapp_product_quantity",
        )
        self.assertEqual(
            self.state.waiting_for,
            "product_quantity",
        )

    def test_published_builder_starts_after_product_selection(self):
        self.publish_builder([
            {
                "key": "customer_name",
                "question": "What is your name?",
                "field_type": "text",
                "order": 1,
            },
        ])

        response = self.select_product()

        self.assertIn("What is your name?", response)

        self.state.refresh_from_db()

        self.assertEqual(
            self.state.current_step,
            "whatsapp_product_builder",
        )
        self.assertEqual(
            self.state.waiting_for,
            "product_conversation_question",
        )

        self.assertEqual(
            self.state.data["selected_whatsapp_product_id"],
            self.product.pk,
        )

        self.assertIn(
            "product_conversation",
            self.state.data,
        )

    def test_builder_answers_advance_and_return_to_quantity(self):
        self.publish_builder([
            {
                "key": "customer_name",
                "question": "What is your name?",
                "field_type": "text",
                "order": 1,
            },
            {
                "key": "delivery_location",
                "question": "Where should we deliver?",
                "field_type": "text",
                "order": 2,
            },
        ])

        self.select_product()

        from whatsapp.views import handle_whatsapp_product_conversation

        first_response = handle_whatsapp_product_conversation(
            "Amina",
            self.organization,
            self.state,
        )

        self.assertIn("Where should we deliver?", first_response)

        self.state.refresh_from_db()

        answers = self.state.data["product_conversation"]["answers"]

        self.assertEqual(answers["customer_name"], "Amina")

        second_response = handle_whatsapp_product_conversation(
            "Dar es Salaam",
            self.organization,
            self.state,
        )

        self.assertIn("Unahitaji kiasi gani?", second_response)

        self.state.refresh_from_db()

        self.assertEqual(
            self.state.current_step,
            "whatsapp_product_quantity",
        )
        self.assertEqual(
            self.state.waiting_for,
            "product_quantity",
        )

        answers = self.state.data["product_conversation"]["answers"]

        self.assertEqual(
            answers["delivery_location"],
            "Dar es Salaam",
        )

    @patch.dict(
        "os.environ",
        {
            "OPENAI_API_KEY": "test-api-key",
            "OPENAI_MODEL": "test-model",
        },
    )
    def test_ai_extracts_and_saves_multiple_builder_answers(self):
        """A successful mocked AI response is validated and saved by Django."""
        self.publish_builder([
            {
                "key": "customer_name",
                "question": "What is your name?",
                "field_type": "text",
                "order": 1,
            },
            {
                "key": "quantity",
                "question": "How many pieces do you need?",
                "field_type": "number",
                "order": 2,
            },
            {
                "key": "delivery_location",
                "question": "Where should we deliver?",
                "field_type": "text",
                "order": 3,
            },
        ])

        self.select_product()

        from whatsapp.views import handle_whatsapp_product_conversation

        ai_response = SimpleNamespace(
            output_text=json.dumps(
                {
                    "answers": {
                        "customer_name": "Amina",
                        "quantity": "10",
                        "delivery_location": "Dar es Salaam",
                    }
                },
                ensure_ascii=False,
            ),
            status="completed",
        )

        with patch("whatsapp.ai_service.OpenAI") as mock_openai:
            mock_client = mock_openai.return_value
            mock_client.responses.create.return_value = ai_response

            response = handle_whatsapp_product_conversation(
                "My name is Amina, I need 10 pieces, and delivery is in Dar es Salaam.",
                self.organization,
                self.state,
            )

        mock_openai.assert_called_once()
        mock_client.responses.create.assert_called_once()

        request = mock_client.responses.create.call_args.kwargs
        sent_context = json.loads(request["input"])
        self.assertEqual(
            sent_context["required_response_format"],
            "JSON",
        )

        self.state.refresh_from_db()
        namespace = self.state.data["product_conversation"]
        answers = namespace["answers"]

        self.assertEqual(answers["customer_name"], "Amina")
        self.assertEqual(answers["quantity"], 10)
        self.assertEqual(answers["delivery_location"], "Dar es Salaam")

        # All three configured questions were answered, so the existing
        # workflow must return to its quantity step.
        self.assertEqual(
            self.state.current_step,
            "whatsapp_product_quantity",
        )
        self.assertEqual(
            self.state.waiting_for,
            "product_quantity",
        )
        self.assertIsNotNone(response)

