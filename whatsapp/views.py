from django.shortcuts import render

# Create your views here.
from django.http import HttpResponse, JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.conf import settings
import json


@csrf_exempt
def webhook(request):
    # Meta webhook verification
    if request.method == "GET":
        verify_token = request.GET.get("hub.verify_token")
        challenge = request.GET.get("hub.challenge")

        if verify_token == settings.WHATSAPP_VERIFY_TOKEN:
            return HttpResponse(challenge)

        return HttpResponse("Invalid verify token", status=403)

    # Incoming WhatsApp messages
    if request.method == "POST":
        try:
            data = json.loads(request.body)

            print("WhatsApp Webhook Received:")
            print(json.dumps(data, indent=2))

            return JsonResponse({"status": "ok"})

        except json.JSONDecodeError:
            return JsonResponse({"error": "Invalid JSON"}, status=400)

    return HttpResponse(status=405)