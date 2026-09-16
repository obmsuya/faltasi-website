import os
import uuid

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "faltasi_website.settings")

import django
django.setup()

from types import SimpleNamespace
from django.test import Client

from customers.models import Customer
from whatsapp.models import Conversation, ConversationState, Message
import whatsapp.views as whatsapp_views


# =========================================================
# TEMPORARY FAKE WHATSAPP SENDER
# =========================================================

def fake_send_whatsapp_message(phone_number, message):
    fake_id = f"test-{uuid.uuid4()}"

    print("\nFAKE OUTGOING WHATSAPP MESSAGE")
    print("To:", phone_number)
    print("Message:", message)

    return SimpleNamespace(
        status_code=200,
        json=lambda: {
            "messages": [
                {"id": fake_id}
            ]
        }
    )


whatsapp_views.send_whatsapp_message = fake_send_whatsapp_message


# =========================================================
# CREATE FRESH TEST CUSTOMER + CONVERSATION
# =========================================================

phone = f"255700{uuid.uuid4().hex[:6]}"

customer = Customer.objects.create(
    name="CCTV Test Customer",
    phone=phone,
    customer_type="individual",
    country="Tanzania",
    preferred_contact_method="whatsapp",
)

conversation = Conversation.objects.create(
    customer=customer,
    phone_number=phone,
    whatsapp_user_id=phone,
    status="active",
)

ConversationState.objects.create(
    conversation=conversation,
    current_step="new",
    waiting_for=None,
    data={}
)

print("\n========================================")
print("NEW TEST")
print("========================================")
print("Customer:", customer)
print("Phone:", phone)
print("Conversation ID:", conversation.id)


# =========================================================
# TEST CLIENT
# =========================================================

client = Client()


def send_test_message(text, number):

    message_id = f"incoming-{uuid.uuid4()}"

    payload = {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "changes": [
                    {
                        "field": "messages",
                        "value": {
                            "contacts": [
                                {
                                    "wa_id": phone,
                                    "profile": {
                                        "name": "CCTV Test Customer"
                                    }
                                }
                            ],
                            "messages": [
                                {
                                    "from": phone,
                                    "id": message_id,
                                    "timestamp": "1760000000",
                                    "type": "text",
                                    "text": {
                                        "body": text
                                    }
                                }
                            ]
                        }
                    }
                ]
            }
        ]
    }

    print("\n========================================")
    print(f"MESSAGE #{number}")
    print("Customer:", text)
    print("========================================")

    response = client.post(
        "/whatsapp/webhook/",
        data=payload,
        content_type="application/json",
    )

    print("Webhook status:", response.status_code)
    print("Webhook response:", response.content.decode())

    conversation.refresh_from_db()
    state = conversation.state

    print("\nSTATE")
    print("Current step:", state.current_step)
    print("Waiting for:", state.waiting_for)
    print("Data:", state.data)

    if conversation.business_request_id:

        request = conversation.business_request
        request.refresh_from_db()

        print("\nBUSINESS REQUEST")
        print("ID:", request.id)
        print("Category:", request.category)
        print("Department:", request.department)
        print("Status:", request.status)
        print("Source:", request.source)
        print("Request text:")
        print(request.request_text)


# =========================================================
# COMPLETE CCTV FLOW
# =========================================================

send_test_message(
    "I need CCTV cameras for my shop.",
    1
)

send_test_message(
    "Mbezi Beach",
    2
)

send_test_message(
    "8 cameras",
    3
)

send_test_message(
    "A retail shop",
    4
)

send_test_message(
    "Yes, I need installation",
    5
)


# =========================================================
# FINAL CHECK
# =========================================================

conversation.refresh_from_db()
state = conversation.state

print("\n\n========================================")
print("FINAL VERIFICATION")
print("========================================")

print("Conversation ID:", conversation.id)
print("Business Request ID:", conversation.business_request_id)
print("Current step:", state.current_step)
print("Waiting for:", state.waiting_for)

print("\nCollected data:")

for key, value in state.data.items():
    print(f"  {key}: {value}")

message_count = Message.objects.filter(
    conversation=conversation
).count()

print("\nMessages saved:", message_count)

print("\n========================================")
print("TEST FINISHED")
print("========================================")