
import hashlib
import hmac
import json
from unittest.mock import patch

from django.test import TestCase, override_settings
from django.urls import reverse

from organizations.models import Organization
from customers.models import Customer

from whatsapp.models import (
    WhatsAppBusinessAccount,
    WhatsAppPhoneNumber,
    Conversation,
    Message,
)


@override_settings(WHATSAPP_APP_SECRET="webhook-test-secret")
class WhatsAppWebhookSecurityTests(TestCase):

    def setUp(self):
        self.organization = Organization.objects.create(
            name="Webhook Test Business",
            organization_type="business",
            status="active",
        )

        self.waba = WhatsAppBusinessAccount.objects.create(
            organization=self.organization,
            waba_id="WEBHOOK_TEST_WABA",
            business_name="Webhook Test WABA",
            status="connected",
            is_active=True,
        )

        self.phone = WhatsAppPhoneNumber.objects.create(
            organization=self.organization,
            whatsapp_business_account=self.waba,
            phone_number_id="WEBHOOK_TEST_PHONE_ID",
            phone_number="255700000111",
            status="connected",
            is_active=True,
        )

        self.customer = Customer.objects.create(
            organization=self.organization,
            name="Webhook Test Customer",
            phone="+255700000222",
        )

        self.url = reverse("whatsapp:webhook")

    def make_payload(self, message=True, status=None):
        value = {
            "messaging_product": "whatsapp",
            "metadata": {
                "display_phone_number": "+255700000111",
                "phone_number_id": "WEBHOOK_TEST_PHONE_ID",
            },
        }

        if message:
            value["messages"] = [{
                "from": "+255700000222",
                "id": "wamid.webhook.security.test",
                "timestamp": "1730000000",
                "type": "text",
                "text": {"body": "Hello"},
            }]

        if status:
            value["statuses"] = [status]

        return {
            "object": "whatsapp_business_account",
            "entry": [{
                "id": "WEBHOOK_TEST_WABA",
                "changes": [{
                    "field": "messages",
                    "value": value,
                }],
            }],
        }

    def post_webhook(self, payload):
        body = json.dumps(payload).encode("utf-8")

        signature = "sha256=" + hmac.new(
            b"webhook-test-secret",
            body,
            hashlib.sha256,
        ).hexdigest()

        return self.client.post(
            self.url,
            data=body,
            content_type="application/json",
            HTTP_X_HUB_SIGNATURE_256=signature,
        )

    @patch("whatsapp.views.send_whatsapp_message", return_value=None)
    def test_active_connection_accepts_incoming_message(self, mock_send):
        response = self.post_webhook(self.make_payload())

        self.assertEqual(response.status_code, 200)

        self.assertTrue(
            Message.objects.filter(
                organization=self.organization,
                conversation__customer=self.customer,
                direction="incoming",
                whatsapp_message_id="wamid.webhook.security.test",
            ).exists()
        )

        mock_send.assert_called_once()

    def test_inactive_phone_rejects_incoming_message(self):
        self.phone.is_active = False
        self.phone.save(update_fields=["is_active"])

        response = self.post_webhook(self.make_payload())

        self.assertEqual(response.status_code, 200)

        self.assertFalse(
            Message.objects.filter(
                whatsapp_message_id="wamid.webhook.security.test",
            ).exists()
        )

    def test_disconnected_phone_rejects_incoming_message(self):
        self.phone.status = "disconnected"
        self.phone.save(update_fields=["status"])

        response = self.post_webhook(self.make_payload())

        self.assertEqual(response.status_code, 200)

        self.assertFalse(
            Message.objects.filter(
                whatsapp_message_id="wamid.webhook.security.test",
            ).exists()
        )

    def test_disconnected_waba_rejects_incoming_message(self):
        self.waba.status = "disconnected"
        self.waba.save(update_fields=["status"])

        response = self.post_webhook(self.make_payload())

        self.assertEqual(response.status_code, 200)

        self.assertFalse(
            Message.objects.filter(
                whatsapp_message_id="wamid.webhook.security.test",
            ).exists()
        )

    def test_inactive_waba_rejects_incoming_message(self):
        self.waba.is_active = False
        self.waba.save(update_fields=["is_active"])

        response = self.post_webhook(self.make_payload())

        self.assertEqual(response.status_code, 200)

        self.assertFalse(
            Message.objects.filter(
                whatsapp_message_id="wamid.webhook.security.test",
            ).exists()
        )

    def test_inactive_organization_rejects_incoming_message(self):
        self.organization.status = "inactive"
        self.organization.save(update_fields=["status"])

        response = self.post_webhook(self.make_payload())

        self.assertEqual(response.status_code, 200)

        self.assertFalse(
            Message.objects.filter(
                whatsapp_message_id="wamid.webhook.security.test",
            ).exists()
        )

    def test_suspended_organization_rejects_incoming_message(self):
        self.organization.status = "suspended"
        self.organization.save(update_fields=["status"])

        response = self.post_webhook(self.make_payload())

        self.assertEqual(response.status_code, 200)

        self.assertFalse(
            Message.objects.filter(
                whatsapp_message_id="wamid.webhook.security.test",
            ).exists()
        )

    def test_disconnected_phone_still_processes_delivery_status(self):
        self.phone.status = "disconnected"
        self.phone.save(update_fields=["status"])

        conversation = Conversation.objects.create(
            organization=self.organization,
            whatsapp_phone_number=self.phone,
            customer=self.customer,
            phone_number=self.customer.phone,
            status="active",
        )

        outgoing_message = Message.objects.create(
            organization=self.organization,
            conversation=conversation,
            direction="outgoing",
            sender_type="faltasi",
            message_type="text",
            content="Test outgoing message",
            whatsapp_message_id="wamid.outgoing.security.test",
            delivery_status="sent",
        )

        payload = self.make_payload(
            message=False,
            status={
                "id": "wamid.outgoing.security.test",
                "status": "delivered",
                "timestamp": "1730000001",
                "recipient_id": "+255700000222",
            },
        )

        response = self.post_webhook(payload)

        self.assertEqual(response.status_code, 200)

        outgoing_message.refresh_from_db()

        self.assertEqual(
            outgoing_message.delivery_status,
            "delivered",
        )
