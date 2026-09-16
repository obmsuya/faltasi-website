
from django.http import HttpResponse, JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.conf import settings
from django.utils import timezone

import json
import requests

from .models import Conversation, ConversationState, Message
from customers.models import Customer


# -----------------------------------------
# SEND WHATSAPP MESSAGE
# -----------------------------------------
def send_whatsapp_message(phone_number, message):

    url = (
        f"https://graph.facebook.com/v26.0/"
        f"{settings.WHATSAPP_PHONE_NUMBER_ID}/messages"
    )

    headers = {
        "Authorization": f"Bearer {settings.WHATSAPP_ACCESS_TOKEN}",
        "Content-Type": "application/json",
    }

    payload = {
        "messaging_product": "whatsapp",
        "to": phone_number,
        "type": "text",
        "text": {
            "body": message
        }
    }

    try:

        response = requests.post(
            url,
            headers=headers,
            json=payload,
            timeout=30
        )

        print(
            "WHATSAPP SEND STATUS:",
            response.status_code
        )

        print(
            "WHATSAPP SEND RESPONSE:",
            response.text
        )

        return response

    except requests.RequestException as e:

        print(
            "WHATSAPP SEND ERROR:",
            str(e)
        )

        return None

def get_or_create_customer(phone_number):
    customer = Customer.objects.filter(
        phone=phone_number
    ).first()

    if customer:
        return customer

    customer = Customer.objects.create(
        phone=phone_number,
        name="WhatsApp Customer",
        country="Tanzania",
    )

    return customer
# -----------------------------------------
# WHATSAPP WEBHOOK
# -----------------------------------------
@csrf_exempt
def webhook(request):

    print(
        "========== WHATSAPP WEBHOOK =========="
    )

    print(
        "METHOD:",
        request.method
    )

    print(
        "PATH:",
        request.path
    )

    print(
        "USER AGENT:",
        request.headers.get("User-Agent")
    )

    # -----------------------------------------
    # META WEBHOOK VERIFICATION
    # -----------------------------------------
    if request.method == "GET":

        verify_token = request.GET.get(
            "hub.verify_token"
        )

        challenge = request.GET.get(
            "hub.challenge"
        )

        print(
            "VERIFY TOKEN:",
            verify_token
        )

        print(
            "CHALLENGE:",
            challenge
        )

        # Meta verification request
        if verify_token and challenge:

            if (
                verify_token
                == settings.WHATSAPP_VERIFY_TOKEN
            ):

                print(
                    "VERIFICATION SUCCESS"
                )

                return HttpResponse(
                    challenge
                )

            print(
                "VERIFICATION FAILED"
            )

            return HttpResponse(
                "Invalid verify token",
                status=403
            )

        # Other GET requests from Meta
        print(
            "GET request received without "
            "verification parameters"
        )

        return HttpResponse(
            "OK",
            status=200
        )

    # -----------------------------------------
    # WHATSAPP WEBHOOK EVENTS
    # -----------------------------------------
    if request.method == "POST":

        print(
            "========== POST RECEIVED =========="
        )

        body = request.body.decode(
            "utf-8",
            errors="replace"
        )

        print(
            "BODY:",
            body
        )

        try:

            data = json.loads(body)

            print("JSON:")

            print(
                json.dumps(
                    data,
                    indent=2
                )
            )

            # -----------------------------------------
            # READ STANDARD WHATSAPP WEBHOOK
            # -----------------------------------------

            entry = data.get(
                "entry",
                []
            )

            if entry:

                changes = entry[0].get(
                    "changes",
                    []
                )

                if changes:

                    value = changes[0].get(
                        "value",
                        {}
                    )

                    # -----------------------------------------
                    # GET MESSAGES
                    # -----------------------------------------

                    messages = value.get(
                        "messages",
                        []
                    )

                    if messages:

                        message = messages[0]

                        sender = message.get(
                            "from"
                        )

                        message_type = message.get(
                            "type"
                        )

                        print(
                            "SENDER:",
                            sender
                        )

                        print(
                            "MESSAGE TYPE:",
                            message_type
                        )

                        # -----------------------------------------
                        # TEXT MESSAGE
                        # -----------------------------------------

                        if message_type == "text":

                            text = (
                                message
                                .get("text", {})
                                .get("body", "")
                            )

                            print(
                                "MESSAGE:",
                                text
                            )

                            # -----------------------------------------
                            # AUTOMATIC REPLY
                            # -----------------------------------------

                            if sender:
                                    # Find or create the Faltasi customer
                                customer = get_or_create_customer(sender)

                            print("CUSTOMER:", customer)

                            reply = process_customer_message(text)

                            print("SENDING AUTOMATIC REPLY...")
                            send_whatsapp_message(sender, reply)

                        # -----------------------------------------
                        # OTHER MESSAGE TYPES
                        # -----------------------------------------

                        else:

                            print(
                                "NON-TEXT MESSAGE RECEIVED"
                            )

                    else:

                        print(
                            "NO WHATSAPP MESSAGE FOUND"
                        )

            else:

                print(
                    "NO WEBHOOK ENTRY FOUND"
                )

            # -----------------------------------------
            # RESPOND TO META
            # -----------------------------------------

            return JsonResponse(
                {
                    "status": "ok"
                }
            )

        except json.JSONDecodeError as e:

            print(
                "JSON ERROR:",
                e
            )

            return JsonResponse(
                {
                    "error": "Invalid JSON"
                },
                status=400
            )

        except Exception as e:

            print(
                "WEBHOOK ERROR:",
                str(e)
            )

            return JsonResponse(
                {
                    "error": "Webhook processing failed"
                },
                status=500
            )

    # -----------------------------------------
    # METHOD NOT ALLOWED
    # -----------------------------------------

    return HttpResponse(
        status=405
    )

def process_customer_message(text):
    """
    Generate a response based on what
    the customer writes.
    """

    text = text.strip()

    if not text:
        return (
            "Thank you for contacting Faltasi Innovations Limited. "
            "Please tell us what you need and we will be happy to help."
        )

    # Convert to lowercase for easier matching
    message = text.lower()

    # Wapangaji Kiganjani
    if any(word in message for word in [
        "wapangaji",
        "tenant",
        "tenants",
        "rent",
        "rental property",
        "property management",
        "landlord"
    ]):
        return (
            "Thank you for your interest in Wapangaji Kiganjani. "
            "It is Faltasi Innovations' property management platform "
            "designed to help landlords manage tenants, rent, properties "
            "and related services.\n\n"
            "Please tell us a little more about your property and what "
            "you would like to manage."
        )

    # CCTV / Security
    if any(word in message for word in [
        "cctv",
        "camera",
        "security camera",
        "surveillance"
    ]):
        return (
            "Thank you. We can assist with CCTV and security solutions.\n\n"
            "Please tell us the location of the property and "
            "what you would like to secure."
        )

    # POS
    if any(word in message for word in [
        "pos",
        "point of sale",
        "cashier system"
    ]):
        return (
            "Thank you for your interest in POS solutions.\n\n"
            "Please tell us what type of business you operate "
            "and what you would like the POS system to help you manage."
        )

    # Computers / laptops
    if any(word in message for word in [
        "laptop",
        "laptops",
        "computer",
        "computers",
        "desktop"
    ]):
        return (
            "Certainly. We can assist with computers and laptops.\n\n"
            "Please tell us how many you need and, if you have one, "
            "your preferred budget or specifications."
        )

    # Networking
    if any(word in message for word in [
        "network",
        "networking",
        "wifi",
        "wi-fi",
        "internet installation"
    ]):
        return (
            "Thank you. We provide networking and ICT solutions.\n\n"
            "Please tell us the location and briefly describe "
            "what you need for your network."
        )

    # Partnership
    if any(word in message for word in [
        "partner",
        "partnership",
        "become a partner"
    ]):
        return (
            "Thank you for your interest in partnering with "
            "Faltasi Innovations Limited.\n\n"
            "Please tell us a little about yourself or your organization "
            "and the type of partnership you are interested in."
        )

    # General quotation request
    if any(word in message for word in [
        "quotation",
        "quote",
        "price",
        "cost",
        "how much"
    ]):
        return (
            "We would be happy to prepare a quotation for you.\n\n"
            "Please describe the product or service you need, "
            "including the quantity or requirements if applicable."
        )

    # Default response
    return (
        "Thank you for contacting Faltasi Innovations Limited. "
        "We have received your request.\n\n"
        "Please provide a little more information about what you need "
        "so we can assist you properly."
    )