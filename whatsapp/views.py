
from django.http import HttpResponse, JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.conf import settings
import json
import requests


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

                                reply = (
                                    "Hello! Welcome to "
                                    "Faltasi Innovations Limited. "
                                    "Thank you for contacting us. "
                                    "How can we help you today?"
                                )

                                print(
                                    "SENDING AUTOMATIC REPLY..."
                                )

                                send_whatsapp_message(
                                    sender,
                                    reply
                                )

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
