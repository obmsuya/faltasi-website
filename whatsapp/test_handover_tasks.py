
from datetime import timedelta
from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone

from customers.models import Customer
from organizations.models import Organization
from whatsapp.models import (
    Conversation,
    Message,
    WhatsAppBusinessAccount,
    WhatsAppPhoneNumber,
)
from whatsapp.tasks import (
    return_handover_to_ai,
    send_handover_reminder,
)
from unittest.mock import patch
from django.contrib.auth import get_user_model

from organizations.models import OrganizationMember


class WhatsAppHandoverTaskTests(TestCase):

    def setUp(self):
        self.organization = Organization.objects.create(
            name="Handover Test Business",
            organization_type="business",
            status="active",
        )

        self.customer = Customer.objects.create(
            organization=self.organization,
            name="Handover Test Customer",
            phone="255700000111",
        )

        self.waba = WhatsAppBusinessAccount.objects.create(
            organization=self.organization,
            waba_id="HANDOVER_TEST_WABA",
            business_name="Handover Test Business",
        )

        self.whatsapp_phone = WhatsAppPhoneNumber.objects.create(
            organization=self.organization,
            whatsapp_business_account=self.waba,
            phone_number_id="HANDOVER_TEST_PHONE_ID",
            phone_number="255700000112",
        )

        self.handover_at = timezone.now()

        self.conversation = Conversation.objects.create(
            organization=self.organization,
            whatsapp_phone_number=self.whatsapp_phone,
            customer=self.customer,
            phone_number=self.customer.phone,
            status="active",
            handling_mode="human",
            handover_at=self.handover_at,
        )

        self.handover_timestamp = self.handover_at.isoformat()

    def add_staff_reply(self):
        Message.objects.create(
            organization=self.organization,
            conversation=self.conversation,
            direction="outgoing",
            sender_type="agent",
            message_type="text",
            content="Our team is assisting you.",
        )

    def test_valid_handover_returns_to_ai(self):
        return_handover_to_ai.run(
            self.conversation.id,
            self.handover_timestamp,
        )

        self.conversation.refresh_from_db()

        self.assertEqual(
            self.conversation.handling_mode,
            "ai",
        )
        self.assertIsNone(self.conversation.handover_at)

    def test_staff_reply_prevents_automatic_ai_return(self):
        self.conversation.handover_at = (
            timezone.now() - timedelta(minutes=30)
        )
        self.conversation.save(update_fields=["handover_at"])

        self.handover_timestamp = self.conversation.handover_at.isoformat()

        self.add_staff_reply()

        return_handover_to_ai.run(
            self.conversation.id,
            self.handover_timestamp,
        )

        self.conversation.refresh_from_db()

        self.assertEqual(
            self.conversation.handling_mode,
            "human",
        )
        self.assertIsNotNone(self.conversation.handover_at)

    def test_closed_conversation_ignores_timeout(self):
        self.conversation.status = "closed"
        self.conversation.save(update_fields=["status"])

        return_handover_to_ai.run(
            self.conversation.id,
            self.handover_timestamp,
        )

        self.conversation.refresh_from_db()

        self.assertEqual(
            self.conversation.handling_mode,
            "human",
        )

    def test_old_handover_timestamp_is_ignored(self):
        old_timestamp = (
            self.handover_at - timedelta(minutes=5)
        ).isoformat()

        return_handover_to_ai.run(
            self.conversation.id,
            old_timestamp,
        )

        self.conversation.refresh_from_db()

        self.assertEqual(
            self.conversation.handling_mode,
            "human",
        )
        self.assertEqual(
            self.conversation.handover_at,
            self.handover_at,
        )

    @patch("whatsapp.tasks.requests.post")
    def test_reminder_is_not_sent_after_staff_reply(self, mock_post):
        self.conversation.handover_at = (
            timezone.now() - timedelta(minutes=15)
        )
        self.conversation.save(update_fields=["handover_at"])

        self.handover_timestamp = self.conversation.handover_at.isoformat()

        self.add_staff_reply()

        with self.settings(
            WHATSAPP_HANDOVER_ALERT_TEMPLATE_NAME="test_handover_alert"
        ):
            send_handover_reminder.run(
                self.conversation.id,
                self.handover_timestamp,
            )

        mock_post.assert_not_called()

    @patch("whatsapp.handover.return_handover_to_ai.apply_async")
    @patch("whatsapp.handover.send_handover_reminder.apply_async")
    def test_handover_schedules_both_timeout_tasks(
        self,
        mock_reminder,
        mock_return,
    ):
        from whatsapp.handover import activate_human_handover

        with self.captureOnCommitCallbacks(execute=True):
            activate_human_handover(self.conversation)

        mock_reminder.assert_called_once()
        mock_return.assert_called_once()

        self.assertEqual(
            mock_reminder.call_args.kwargs["countdown"],
            900,
        )

        self.assertEqual(
            mock_return.call_args.kwargs["countdown"],
            1800,
        )



    @patch("whatsapp.tasks.requests.post")
    @patch("whatsapp.views._get_whatsapp_sender_credentials")
    def test_reminder_only_targets_eligible_opted_in_members(
        self,
        mock_credentials,
        mock_post,
    ):
        User = get_user_model()

        mock_credentials.return_value = (
            "test_access_token",
            "test_phone_number_id",
        )

        mock_response = type(
            "Response",
            (),
            {"status_code": 200, "text": ""},
        )()
        mock_post.return_value = mock_response

        members = [
            {
                "username": "handover_owner",
                "role": "owner",
                "membership_active": True,
                "user_active": True,
                "opt_in": True,
                "phone": "255700000201",
            },
            {
                "username": "handover_manager",
                "role": "manager",
                "membership_active": True,
                "user_active": True,
                "opt_in": True,
                "phone": "255700000202",
            },
            {
                "username": "handover_admin_no_consent",
                "role": "admin",
                "membership_active": True,
                "user_active": True,
                "opt_in": False,
                "phone": "255700000203",
            },
            {
                "username": "handover_agent",
                "role": "agent",
                "membership_active": True,
                "user_active": True,
                "opt_in": True,
                "phone": "255700000204",
            },
            {
                "username": "handover_inactive_member",
                "role": "owner",
                "membership_active": False,
                "user_active": True,
                "opt_in": True,
                "phone": "255700000205",
            },
            {
                "username": "handover_disabled_user",
                "role": "admin",
                "membership_active": True,
                "user_active": False,
                "opt_in": True,
                "phone": "255700000206",
            },
        ]

        for item in members:
            user = User.objects.create_user(
                username=item["username"],
                password="test-password",
                is_active=item["user_active"],
            )

            OrganizationMember.objects.create(
                organization=self.organization,
                user=user,
                role=item["role"],
                is_active=item["membership_active"],
                whatsapp_notifications_opt_in=item["opt_in"],
                phone_number=item["phone"],
            )
        self.whatsapp_phone.status = "connected"
        self.whatsapp_phone.save(update_fields=["status"])
        with self.settings(
            WHATSAPP_HANDOVER_ALERT_TEMPLATE_NAME="test_handover_alert",
            WHATSAPP_HANDOVER_ALERT_LANGUAGE="en_US",
        ):
            send_handover_reminder.run(
                self.conversation.id,
                self.handover_timestamp,
            )

        self.assertEqual(mock_post.call_count, 2)

        sent_numbers = {
            call.kwargs["json"]["to"]
            for call in mock_post.call_args_list
        }

        self.assertEqual(
            sent_numbers,
            {
                "255700000201",
                "255700000202",
            },
        )

