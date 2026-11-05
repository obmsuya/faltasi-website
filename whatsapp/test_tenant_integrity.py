from django.core.exceptions import ValidationError
from django.test import TestCase

from organizations.models import Organization
from customers.models import Customer

from whatsapp.models import (
    WhatsAppBusinessAccount,
    WhatsAppPhoneNumber,
    WhatsAppConnection,
    Conversation,
    Message,
)


class WhatsAppTenantIntegrityTests(TestCase):

    def setUp(self):
        self.org_a = Organization.objects.create(
            name="Organization A",
            organization_type="business",
            status="active",
        )

        self.org_b = Organization.objects.create(
            name="Organization B",
            organization_type="business",
            status="active",
        )

        self.waba_a = WhatsAppBusinessAccount.objects.create(
            organization=self.org_a,
            business_name="WABA A",
        )

        self.waba_b = WhatsAppBusinessAccount.objects.create(
            organization=self.org_b,
            business_name="WABA B",
        )

        self.phone_a = WhatsAppPhoneNumber.objects.create(
            organization=self.org_a,
            whatsapp_business_account=self.waba_a,
            phone_number="+255700000001",
        )

        self.customer_a = Customer.objects.create(
            organization=self.org_a,
            name="Customer A",
            phone="255700000002",
        )

    def test_phone_cannot_use_another_organizations_waba(self):
        phone = WhatsAppPhoneNumber(
            organization=self.org_a,
            whatsapp_business_account=self.waba_b,
            phone_number="+255700000003",
        )

        with self.assertRaises(ValidationError):
            phone.full_clean()

    def test_connection_cannot_use_another_organizations_waba(self):
        connection = WhatsAppConnection(
            organization=self.org_a,
            whatsapp_business_account=self.waba_b,
        )

        with self.assertRaises(ValidationError):
            connection.full_clean()

    def test_conversation_cannot_use_another_organizations_phone(self):
        conversation = Conversation(
            organization=self.org_a,
            whatsapp_phone_number=WhatsAppPhoneNumber.objects.create(
                organization=self.org_b,
                whatsapp_business_account=self.waba_b,
                phone_number="+255700000004",
            ),
            customer=self.customer_a,
            phone_number="255700000002",
        )

        with self.assertRaises(ValidationError):
            conversation.full_clean()

    def test_conversation_cannot_use_another_organizations_customer(self):
        customer_b = Customer.objects.create(
            organization=self.org_b,
            name="Customer B",
            phone="255700000005",
        )

        conversation = Conversation(
            organization=self.org_a,
            whatsapp_phone_number=self.phone_a,
            customer=customer_b,
            phone_number="255700000005",
        )

        with self.assertRaises(ValidationError):
            conversation.full_clean()

    def test_message_cannot_use_another_organizations_conversation(self):
        conversation = Conversation.objects.create(
            organization=self.org_a,
            whatsapp_phone_number=self.phone_a,
            customer=self.customer_a,
            phone_number=self.customer_a.phone,
        )

        message = Message(
            organization=self.org_b,
            conversation=conversation,
            direction="incoming",
            sender_type="customer",
            message_type="text",
            content="Test",
        )

        with self.assertRaises(ValidationError):
            message.full_clean()